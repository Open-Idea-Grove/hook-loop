from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from hook_loop.dsl import DslError, load_loop_spec


@dataclass(frozen=True)
class OpencodeInstallResult:
    planned: list[Path]
    written: list[Path]


def build_opencode_scaffold(
    destination: Path,
    profile: str = "software_delivery",
    dsl_path: Path | str | None = None,
) -> dict[str, str]:
    """Build opencode scaffold files: a JS plugin + hook-loop.json."""
    if dsl_path is not None:
        load_loop_spec(dsl_path)  # validate; raises DslError on failure
        loop_content = Path(dsl_path).read_text(encoding="utf-8")
    elif profile == "software_delivery":
        from hook_loop.codex_scaffold import _software_delivery_loop

        loop_content = json.dumps(_software_delivery_loop(), indent=2, sort_keys=True) + "\n"
    else:
        raise ValueError(f"Unsupported profile without --dsl: {profile}")

    dest = Path(destination).resolve()
    hook_bin = _find_hook_bin(dest)
    config = str(dest / "hook-loop.json")
    event_log = str(dest / ".hook-loop" / "events.jsonl")

    plugin = _hook_loop_plugin(hook_bin, config, event_log)
    return {
        ".opencode/plugins/hook_loop.js": plugin,
        "hook-loop.json": loop_content,
    }


def install_opencode_scaffold(
    profile: str,
    destination: Path,
    dry_run: bool = True,
    dsl_path: Path | str | None = None,
) -> OpencodeInstallResult:
    base = Path(destination)
    files = build_opencode_scaffold(destination=base, profile=profile, dsl_path=dsl_path)
    planned = [base / relative for relative in files]
    if dry_run:
        return OpencodeInstallResult(planned=planned, written=[])

    written: list[Path] = []
    for relative, content in files.items():
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return OpencodeInstallResult(planned=planned, written=written)


def _find_hook_bin(dest: Path) -> str:
    """Find the hook-loop executable, preferring an absolute path."""
    import shutil
    import sys

    # 1. Check .venv/bin/hook-loop relative to destination
    venv_bin = dest / ".venv" / "bin" / "hook-loop"
    if venv_bin.exists():
        return str(venv_bin)
    # 2. Check shutil.which
    which = shutil.which("hook-loop")
    if which:
        return which
    # 3. Fallback to relative (user must ensure it's on PATH)
    return "hook-loop"


def _hook_loop_plugin(hook_bin: str, config: str, event_log: str) -> str:
    return f"""const HOOK_BIN = {json.dumps(hook_bin)};
const CONFIG = {json.dumps(config)};
const EVENT_LOG = {json.dumps(event_log)};

async function callHookLoop(event, payload) {{
  const input = JSON.stringify(payload);
  try {{
    const proc = Bun.spawn({{
      cmd: [HOOK_BIN, "opencode-hook", "--event", event, "--config", CONFIG, "--event-log", EVENT_LOG],
      stdin: new TextEncoder().encode(input),
      stdout: "pipe",
      stderr: "pipe",
    }});
    const exitCode = await proc.exited;
    const stdout = await new Response(proc.stdout).text();
    const stderr = await new Response(proc.stderr).text();
    return {{ exitCode, stdout, stderr }};
  }} catch (err) {{
    return {{ exitCode: err.exitCode ?? 1, stdout: "", stderr: String(err) }};
  }}
}}

function enforceHookDecision(result, fallbackMessage) {{
  if (result.exitCode === 2) {{
    throw new Error(result.stdout || fallbackMessage);
  }}
}}

export const HookLoopPlugin = async ({{ project, client, directory, worktree }}) => {{
  const sessionId = project?.id ?? "opencode-session";
  const cwd = directory ?? "";

  // session.created is handled by the event handler; do not block init (#14 fix).

  return {{
    "tool.execute.before": async (input, output) => {{
      const payload = {{
        session_id: sessionId,
        cwd,
        tool: input?.tool ?? input?.name ?? "unknown",
        input: output?.args ?? {{}},
        workspace: worktree,
      }};
      const result = await callHookLoop("tool.execute.before", payload);
      enforceHookDecision(result, "blocked by hook-loop policy");
    }},
    "tool.execute.after": async (input, output) => {{
      const payload = {{
        session_id: sessionId,
        cwd,
        tool: input?.tool ?? input?.name ?? "unknown",
        input: output?.args ?? input?.args ?? {{}},
        output: {{
          exit_code: output?.exitCode ?? output?.exit_code ?? 0,
          stdout: output?.stdout ?? output?.output ?? "",
        }},
        workspace: worktree,
      }};
      await callHookLoop("tool.execute.after", payload);
    }},
    event: async ({{ event }}) => {{
      const eventType = event?.type ?? "";
      if (eventType === "session.idle" || (eventType === "session.status" && event?.properties?.status === "idle")) {{
        const payload = {{ session_id: sessionId, cwd, workspace: worktree }};
        const result = await callHookLoop("session.idle", payload);
        enforceHookDecision(result, "blocked by hook-loop stop policy");
        return;
      }}
      if (eventType === "session.created" || eventType === "session.init") {{
        const payload = {{ session_id: sessionId, cwd, workspace: worktree }};
        await callHookLoop("session.created", payload);
        return;
      }}
      // message.updated: role is inside properties.info.role (#18 fix).
      // Fire with empty text so prompt_not_match rules still trigger.
      if (eventType === "message.updated") {{
        const info = event?.properties?.info ?? {{}};
        const role = info.role ?? "";
        if (role === "user" || role === "assistant") {{
          const payload = {{ session_id: sessionId, cwd, text: "", workspace: worktree }};
          await callHookLoop("message.updated", payload);
        }}
      }}
      // message.part.updated: carries actual text content.
      if (eventType === "message.part.updated") {{
        const part = event?.properties?.part ?? event?.properties?.info ?? {{}};
        const text = part.text ?? part.content ?? "";
        const role = part.role ?? event?.properties?.info?.role ?? "";
        if (text && (role === "user" || role === "assistant")) {{
          const payload = {{ session_id: sessionId, cwd, text, workspace: worktree }};
          await callHookLoop("message.updated", payload);
        }}
      }}
    }},
  }};
}};
"""

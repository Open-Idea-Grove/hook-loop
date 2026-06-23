from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from hook_loop.dsl import DslError, load_loop_spec


@dataclass(frozen=True)
class CodexInstallResult:
    planned: list[Path]
    written: list[Path]


def build_codex_scaffold(
    profile: str,
    command_prefix: str = "hook-loop",
    dsl_path: Path | str | None = None,
) -> dict[str, str]:
    if dsl_path is None and profile != "software_delivery":
        raise ValueError(f"Unsupported Codex profile: {profile}")
    hook_command = _hook_command(command_prefix)
    hooks = {
        "hooks": {
            "SessionStart": [_hook_group("startup|resume|clear|compact", hook_command, "SessionStart")],
            "UserPromptSubmit": [_hook_group(None, hook_command, "UserPromptSubmit")],
            "PreToolUse": [_hook_group("Bash|apply_patch|Edit|Write|mcp__.*", hook_command, "PreToolUse")],
            "PermissionRequest": [_hook_group("Bash|apply_patch|Edit|Write|mcp__.*", hook_command, "PermissionRequest")],
            "PostToolUse": [_hook_group("Bash|apply_patch|Edit|Write|mcp__.*", hook_command, "PostToolUse")],
            "PreCompact": [_hook_group("manual|auto", hook_command, "PreCompact")],
            "PostCompact": [_hook_group("manual|auto", hook_command, "PostCompact")],
            "Stop": [_hook_group(None, hook_command, "Stop")],
        }
    }
    if dsl_path is not None:
        load_loop_spec(dsl_path)  # validate; raises DslError on failure
        loop_content = Path(dsl_path).read_text(encoding="utf-8")
    else:
        loop_content = json.dumps(_software_delivery_loop(), indent=2, sort_keys=True) + "\n"
    return {
        ".codex/hooks.json": json.dumps(hooks, indent=2, sort_keys=True) + "\n",
        "hook-loop.json": loop_content,
    }


def install_codex_scaffold(
    profile: str,
    target: str,
    destination: Path,
    dry_run: bool = True,
    dsl_path: Path | str | None = None,
) -> CodexInstallResult:
    if target not in {"project", "user", "directory"}:
        raise ValueError("target must be project, user, or directory")
    base = Path(destination)
    files = build_codex_scaffold(profile, dsl_path=dsl_path)
    planned = [base / relative for relative in files]
    if dry_run:
        return CodexInstallResult(planned=planned, written=[])

    written: list[Path] = []
    for relative, content in files.items():
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return CodexInstallResult(planned=planned, written=written)


def _hook_group(matcher: str | None, hook_command: str, event_name: str) -> dict:
    command = f"{hook_command} --event {event_name} --config hook-loop.json --event-log .hook-loop/events.jsonl"
    group = {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 30,
                "statusMessage": f"hook-loop {event_name}",
            }
        ]
    }
    if matcher is not None:
        group["matcher"] = matcher
    return group


def _hook_command(command_prefix: str) -> str:
    if command_prefix == "hook-loop":
        return "hook-loop codex-hook"
    return f"{command_prefix} codex-hook"


def _software_delivery_loop() -> dict:
    return {
        "loop": {
            "id": "software_delivery",
            "initial_state": "backlog",
            "states": ["backlog", "building", "evidence_ready", "evaluating", "done", "stopped"],
            "terminal_states": ["done", "stopped"],
            "stop_state": "stopped",
            "events": ["feature_selected", "evidence_recorded", "review_requested", "evaluator_passed"],
            "transitions": [
                {"from": "backlog", "event": "feature_selected", "to": "building"},
                {"from": "building", "event": "evidence_recorded", "to": "evidence_ready"},
                {"from": "evidence_ready", "event": "review_requested", "to": "evaluating"},
                {
                    "from": "evaluating",
                    "event": "evaluator_passed",
                    "to": "done",
                    "guards": ["evidence_bound_to_criteria"],
                },
            ],
        },
        "simulation": {
            "budget": {"max_turns": 3, "max_no_progress_turns": 1},
            "agent_steps": {
                "backlog": [{"event": "feature_selected"}],
                "building": [{"event": "evidence_recorded", "payload": {"evidence_id": "e1"}}],
                "evidence_ready": [{"event": "review_requested"}],
            },
            "verdicts": [{"status": "PASS", "details": "evidence checked"}],
        },
        "codex": {
            "event_map": [
                {
                    "codex_event": "UserPromptSubmit",
                    "when": {"prompt_not_match": "(?i)verdict"},
                    "emit": "feature_selected",
                    "comment": "first non-verdict prompt kicks off backlog->building",
                },
                {
                    "codex_event": "PostToolUse",
                    "when": {
                        "tool_name": "Bash",
                        "command_match": "pytest|test|git diff --check|lint|mypy",
                        "exit_code": 0,
                    },
                    "record": {
                        "event_type": "evidence_registered",
                        "actor": "codex",
                        "payload": {"kind": "verification"},
                        "include": ["command", "exit_code", "stdout"],
                    },
                    "emit": "evidence_recorded",
                    "comment": "building->evidence_ready",
                },
                {
                    "codex_event": "UserPromptSubmit",
                    "when": {"prompt_match": "(?i)verdict.*PASS|PASS.*verdict"},
                    "record": {
                        "event_type": "verdict_recorded",
                        "actor": "evaluator",
                        "payload": {"status": "PASS"},
                        "include": ["prompt"],
                    },
                    "emit": "review_requested",
                    "comment": "evidence_ready->evaluating",
                },
                {
                    "codex_event": "UserPromptSubmit",
                    "when": {"prompt_match": "(?i)verdict.*PASS|PASS.*verdict"},
                    "emit": "evaluator_passed",
                    "guard_satisfied": ["evidence_bound_to_criteria"],
                    "comment": "evaluating->done (guard satisfied by recorded evidence)",
                },
            ]
        },
    }

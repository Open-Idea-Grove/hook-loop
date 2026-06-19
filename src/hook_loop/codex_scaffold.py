from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CodexInstallResult:
    planned: list[Path]
    written: list[Path]


def build_codex_scaffold(profile: str, command_prefix: str = "hook-loop") -> dict[str, str]:
    if profile != "software_delivery":
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
    return {
        ".codex/hooks.json": json.dumps(hooks, indent=2, sort_keys=True) + "\n",
        ".codex/hooks/hook_loop_codex.py": _hook_script(),
        "hook-loop.json": json.dumps(_software_delivery_loop(), indent=2, sort_keys=True) + "\n",
    }


def install_codex_scaffold(
    profile: str,
    target: str,
    destination: Path,
    dry_run: bool = True,
) -> CodexInstallResult:
    if target not in {"project", "user", "directory"}:
        raise ValueError("target must be project, user, or directory")
    base = Path(destination)
    files = build_codex_scaffold(profile)
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


def _hook_script() -> str:
    return """#!/usr/bin/env python3
\"\"\"Placeholder hook-loop Codex command hook.

The generated hooks.json calls `hook-loop codex-hook` directly. This file is
included so project installs have a predictable place for future wrapper logic.
\"\"\"

raise SystemExit(0)
"""


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
    }

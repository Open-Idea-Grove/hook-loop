from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from hook_loop.events import new_event
from hook_loop.hooks import HookContext, HookDecision
from hook_loop.store import JsonlEventLog


SUPPORTED_CODEX_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "Stop",
    "PreCompact",
    "PostCompact",
}


@dataclass(frozen=True)
class CodexHookResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


def normalize_codex_hook_input(event_name: str, raw_input: dict[str, Any]) -> HookContext:
    if event_name not in SUPPORTED_CODEX_EVENTS:
        raise ValueError(f"Unsupported Codex hook event: {event_name}")
    tool_input = _dict_value(raw_input.get("tool_input") or raw_input.get("input"))
    return HookContext(
        state=str(raw_input.get("state") or "unknown"),
        event=_normalized_event(event_name),
        payload={
            "hook_event_name": event_name,
            "tool_output": raw_input.get("tool_output") or raw_input.get("output"),
            "prompt": raw_input.get("prompt") or raw_input.get("user_prompt"),
        },
        platform="codex",
        hook_event_name=event_name,
        session_id=str(raw_input.get("session_id") or raw_input.get("thread_id") or "default"),
        run_id=str(raw_input.get("run_id") or raw_input.get("turn_id") or uuid4()),
        cwd=str(raw_input.get("cwd") or Path.cwd()),
        tool_name=_optional_str(raw_input.get("tool_name") or raw_input.get("tool")),
        tool_input=tool_input,
        raw_input=dict(raw_input),
    )


def handle_codex_hook(
    event_name: str,
    raw_input: dict[str, Any],
    store: JsonlEventLog,
) -> CodexHookResult:
    context = normalize_codex_hook_input(event_name, raw_input)
    decision = _decide(context, store)
    _record_hook_event(store, context, decision)
    if event_name == "Stop" and not decision.allowed:
        _record_stop_contract_failed(store, context, decision)
    if decision.allowed:
        return CodexHookResult(0, _json_stdout({"decision": decision.verdict, "messages": decision.messages}))
    return CodexHookResult(2, "\n".join(decision.messages))


def _decide(context: HookContext, store: JsonlEventLog) -> HookDecision:
    if context.hook_event_name in {"PreToolUse", "PermissionRequest"}:
        return _pre_action_decision(context)
    if context.hook_event_name == "PostToolUse":
        return _record_post_tool_evidence(context, store)
    if context.hook_event_name == "UserPromptSubmit":
        return _record_user_prompt(context, store)
    if context.hook_event_name == "Stop":
        return _stop_decision(context, store)
    if context.hook_event_name in {"SessionStart", "PreCompact", "PostCompact"}:
        return HookDecision.steer(_session_contract_message(context))
    return HookDecision.allow()


def _pre_action_decision(context: HookContext) -> HookDecision:
    tool_name = context.tool_name or ""
    tool_input = context.tool_input or {}
    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        if _is_risky_shell_command(command):
            return HookDecision.block("risky action blocked by hook-loop policy")
    if tool_name in {"apply_patch", "Edit", "Write"}:
        patch_text = " ".join(str(value) for value in tool_input.values())
        if _references_protected_path(patch_text):
            return HookDecision.block("protected path write blocked by hook-loop policy")
    return HookDecision.allow()


def _record_post_tool_evidence(context: HookContext, store: JsonlEventLog) -> HookDecision:
    command = str((context.tool_input or {}).get("command", ""))
    output = _dict_value(context.payload.get("tool_output"))
    exit_code = output.get("exit_code")
    if context.tool_name == "Bash" and _is_verification_command(command) and exit_code in {0, "0", None}:
        store.append(
            new_event(
                session_id=context.session_id or "default",
                run_id=context.run_id or str(uuid4()),
                state=context.state,
                event_type="evidence_registered",
                actor="codex",
                payload={
                    "kind": "verification",
                    "command": command,
                    "exit_code": exit_code,
                    "stdout": str(output.get("stdout", ""))[:2000],
                },
            )
        )
    return HookDecision.allow()


def _record_user_prompt(context: HookContext, store: JsonlEventLog) -> HookDecision:
    prompt = str(context.payload.get("prompt") or "")
    if "PASS" in prompt and "verdict" in prompt.lower():
        store.append(
            new_event(
                session_id=context.session_id or "default",
                run_id=context.run_id or str(uuid4()),
                state=context.state,
                event_type="verdict_recorded",
                actor="evaluator",
                payload={"status": "PASS", "details": prompt[:2000]},
            )
        )
    return HookDecision.allow()


def _stop_decision(context: HookContext, store: JsonlEventLog) -> HookDecision:
    events = [event for event in store.read_all() if event.session_id == (context.session_id or "default")]
    has_evidence = any(event.event_type == "evidence_registered" for event in events)
    has_verification = any(
        event.event_type == "evidence_registered" and event.payload.get("kind") == "verification" for event in events
    )
    has_evaluator_pass = any(
        event.event_type == "verdict_recorded" and event.payload.get("status") == "PASS" for event in events
    )
    missing: list[str] = []
    if not has_evidence:
        missing.append("record evidence")
    if not has_verification:
        missing.append("run and record verification")
    if not has_evaluator_pass:
        missing.append("obtain fresh evaluator PASS")
    if not missing:
        return HookDecision.allow()

    message = "Cannot stop yet. Required next steps: " + "; ".join(missing) + "."
    return HookDecision.replan(message)


def _record_stop_contract_failed(store: JsonlEventLog, context: HookContext, decision: HookDecision) -> None:
    store.append(
        new_event(
            session_id=context.session_id or "default",
            run_id=context.run_id or str(uuid4()),
            state=context.state,
            event_type="stop_contract_failed",
            actor="hook-loop",
            payload={"message": "\n".join(decision.messages), "messages": decision.messages},
        )
    )


def _record_hook_event(store: JsonlEventLog, context: HookContext, decision: HookDecision) -> None:
    store.append(
        new_event(
            session_id=context.session_id or "default",
            run_id=context.run_id or str(uuid4()),
            state=context.state,
            event_type="hook_fired",
            actor="hook-loop",
            payload={
                "platform": "codex",
                "hook_event_name": context.hook_event_name,
                "tool_name": context.tool_name,
                "verdict": decision.verdict,
                "allowed": decision.allowed,
                "messages": decision.messages,
            },
        )
    )


def _normalized_event(event_name: str) -> str | None:
    if event_name in {"PreToolUse", "PermissionRequest"}:
        return "action_requested"
    if event_name == "PostToolUse":
        return "action_completed"
    if event_name == "Stop":
        return "stop_requested"
    if event_name == "UserPromptSubmit":
        return "prompt_submitted"
    if event_name == "SessionStart":
        return "session_started"
    if event_name in {"PreCompact", "PostCompact"}:
        return event_name.lower()
    return None


def _is_risky_shell_command(command: str) -> bool:
    stripped = command.strip()
    risky_prefixes = ("rm ", "sudo rm", "git reset", "git push", "git commit", "drop ")
    if stripped.startswith(risky_prefixes):
        return True
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        tokens = stripped.split()
    return any(token in {".git", ".git/", ".git/config"} for token in tokens) or ".git" in stripped and "rm" in tokens


def _references_protected_path(text: str) -> bool:
    return any(part in text for part in (".git/", ".git\\", "/.git", " .git"))


def _is_verification_command(command: str) -> bool:
    lowered = command.lower()
    return any(marker in lowered for marker in ("pytest", "test", "git diff --check", "lint", "mypy"))


def _session_contract_message(context: HookContext) -> str:
    return (
        "hook-loop software_delivery contract active: produce evidence, run verification, "
        "and require fresh evaluator PASS before final Stop."
    )


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _json_stdout(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True)

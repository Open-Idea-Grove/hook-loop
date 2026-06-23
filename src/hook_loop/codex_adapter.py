from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from hook_loop.codex_mapping import SUPPORTED_CODEX_EVENTS, CodexEventMap, RecordSpec, ResolvedRule
from hook_loop.driver import EventSourcedLoopDriver
from hook_loop.dsl import LoopSpec
from hook_loop.events import new_event
from hook_loop.hooks import HookContext, HookDecision
from hook_loop.store import JsonlEventLog


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
    spec: LoopSpec,
) -> CodexHookResult:
    context = normalize_codex_hook_input(event_name, raw_input)
    driver = EventSourcedLoopDriver(spec.definition, store, _session_id(context))

    if event_name in {"PreToolUse", "PermissionRequest"}:
        decision = _pre_action_decision(context)
    elif event_name == "Stop":
        decision = _stop_decision(driver)
    elif event_name in {"SessionStart", "PreCompact", "PostCompact"}:
        if spec.codex is not None and spec.codex.resolve(context):
            decision = _apply_mapping(context, driver, spec.codex, store)
        else:
            decision = HookDecision.steer(_session_contract_message(context))
    else:
        decision = _apply_mapping(context, driver, spec.codex, store)

    _record_hook_event(store, context, decision, driver.current_state)
    if event_name == "Stop" and not decision.allowed:
        _record_stop_contract_failed(store, context, decision, driver.current_state)
    return _to_codex_result(decision)


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


def _stop_decision(driver: EventSourcedLoopDriver) -> HookDecision:
    if driver.is_terminal():
        return HookDecision.allow()
    next_events = sorted(
        {transition.event for transition in driver.definition.transitions if transition.from_state == driver.current_state}
    )
    steps = "record evidence; run and record verification; obtain fresh evaluator PASS"
    if next_events:
        detail = f"Next events from {driver.current_state}: {', '.join(next_events)}"
    else:
        detail = "no outgoing transition from current state"
    return HookDecision.replan(f"Cannot stop yet. Required next steps: {steps}. {detail}")


def _apply_mapping(
    context: HookContext,
    driver: EventSourcedLoopDriver,
    mapping: CodexEventMap | None,
    store: JsonlEventLog,
) -> HookDecision:
    if mapping is None:
        return HookDecision.allow()
    rules = mapping.resolve(context)
    if not rules:
        return HookDecision.allow()

    emitted = False
    rejected_any = False
    messages: list[str] = []
    for rule in rules:
        if rule.record is not None:
            _record_side_event(store, context, rule.record, driver.current_state)
        result = driver.apply_event(rule.emit, {}, explicit_guards=set(rule.guard_satisfied))
        if result.applied:
            emitted = True
        elif result.rejected:
            rejected_any = True
            if result.reason:
                messages.append(f"{rule.emit}: {result.reason}")

    if emitted:
        return HookDecision.allow()
    if rejected_any:
        return HookDecision.steer("; ".join(messages) or "no transition applied; continue working")
    return HookDecision.allow()


def _record_side_event(store: JsonlEventLog, context: HookContext, record: RecordSpec, state: str) -> None:
    payload = dict(record.payload)
    for key in record.include:
        if key == "command":
            payload["command"] = str((context.tool_input or {}).get("command", ""))
        elif key == "exit_code":
            output = context.payload.get("tool_output") or {}
            payload["exit_code"] = output.get("exit_code") if isinstance(output, dict) else None
        elif key == "stdout":
            output = context.payload.get("tool_output") or {}
            payload["stdout"] = str(output.get("stdout", "") if isinstance(output, dict) else "")[:2000]
        elif key == "prompt":
            payload["prompt"] = str(context.payload.get("prompt") or "")[:2000]
    store.append(
        new_event(
            session_id=_session_id(context),
            run_id=context.run_id or str(uuid4()),
            state=state,
            event_type=record.event_type,
            actor=record.actor,
            payload=payload,
        )
    )


def _record_stop_contract_failed(
    store: JsonlEventLog, context: HookContext, decision: HookDecision, state: str
) -> None:
    store.append(
        new_event(
            session_id=_session_id(context),
            run_id=context.run_id or str(uuid4()),
            state=state,
            event_type="stop_contract_failed",
            actor="hook-loop",
            payload={"message": "\n".join(decision.messages), "messages": decision.messages},
        )
    )


def _record_hook_event(
    store: JsonlEventLog, context: HookContext, decision: HookDecision, state: str
) -> None:
    store.append(
        new_event(
            session_id=_session_id(context),
            run_id=context.run_id or str(uuid4()),
            state=state,
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


def _to_codex_result(decision: HookDecision) -> CodexHookResult:
    if decision.allowed:
        return CodexHookResult(0, _json_stdout({"decision": decision.verdict, "messages": decision.messages}))
    return CodexHookResult(2, "\n".join(decision.messages))


def _session_id(context: HookContext) -> str:
    return context.session_id or "default"


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

from __future__ import annotations

from pathlib import Path
from typing import Any

from hook_loop.codex_adapter import CodexHookResult, handle_codex_hook, normalize_codex_hook_input
from hook_loop.dsl import LoopSpec
from hook_loop.hooks import HookContext
from hook_loop.store import JsonlEventLog


OPENCODE_TO_CODEX_EVENTS = {
    "tool.execute.before": "PreToolUse",
    "tool.execute.after": "PostToolUse",
    "session.idle": "Stop",
    "message.updated": "UserPromptSubmit",
    "session.created": "SessionStart",
}

TOOL_NAME_MAP = {
    "bash": "Bash",
    "write": "Write",
    "edit": "Edit",
    "read": "Read",
    "grep": "Grep",
    "glob": "Glob",
    "todo_write": "TodoWrite",
    "todowrite": "TodoWrite",
    "webfetch": "WebFetch",
    "web_fetch": "WebFetch",
    "multi_edit": "MultiEdit",
    "multiedit": "MultiEdit",
    "apply_patch": "apply_patch",
}


def normalize_opencode_hook_input(event_name: str, raw_input: dict[str, Any]) -> HookContext:
    translated_event = _translate_event_name(event_name)
    return normalize_codex_hook_input(translated_event, _translate_input(event_name, raw_input))


def handle_opencode_hook(
    event_name: str,
    raw_input: dict[str, Any],
    store: JsonlEventLog,
    spec: LoopSpec,
) -> CodexHookResult:
    translated_event = _translate_event_name(event_name)
    translated_input = _translate_input(event_name, raw_input)
    return handle_codex_hook(translated_event, translated_input, store, spec)


def _translate_event_name(event_name: str) -> str:
    try:
        return OPENCODE_TO_CODEX_EVENTS[event_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported opencode hook event: {event_name}") from exc


def _translate_input(event_name: str, raw_input: dict[str, Any]) -> dict[str, Any]:
    translated = dict(raw_input)
    translated["platform"] = "opencode"
    translated["opencode_event_name"] = event_name

    session_id = _session_id(raw_input)
    if session_id is not None:
        translated["session_id"] = session_id

    run_id = _run_id(raw_input)
    if run_id is not None:
        translated["run_id"] = run_id

    translated["cwd"] = str(raw_input.get("cwd") or raw_input.get("workspace") or Path.cwd())

    tool_name = _tool_name(raw_input)
    if tool_name is not None:
        translated["tool_name"] = normalize_opencode_tool_name(tool_name)

    tool_input = _tool_input(raw_input)
    if tool_input is not None:
        translated["tool_input"] = tool_input

    tool_output = _tool_output(raw_input)
    if tool_output is not None:
        translated["tool_output"] = tool_output

    prompt = _prompt(raw_input)
    if prompt is not None:
        translated["prompt"] = prompt

    return translated


def normalize_opencode_tool_name(tool_name: str) -> str:
    normalized = tool_name.strip()
    key = normalized.replace("-", "_").lower()
    if key in TOOL_NAME_MAP:
        return TOOL_NAME_MAP[key]
    if "_" in key:
        return "".join(part.capitalize() for part in key.split("_") if part)
    if normalized and normalized[0].islower():
        return normalized[:1].upper() + normalized[1:]
    return normalized


def _session_id(raw_input: dict[str, Any]) -> str | None:
    if raw_input.get("session_id") is not None:
        return str(raw_input["session_id"])
    session = raw_input.get("session")
    if isinstance(session, dict) and session.get("id") is not None:
        return str(session["id"])
    return None


def _run_id(raw_input: dict[str, Any]) -> str | None:
    for key in ("run_id", "message_id", "event_id", "turn_id"):
        if raw_input.get(key) is not None:
            return str(raw_input[key])
    message = raw_input.get("message")
    if isinstance(message, dict) and message.get("id") is not None:
        return str(message["id"])
    return None


def _tool_name(raw_input: dict[str, Any]) -> str | None:
    for key in ("tool_name", "tool"):
        value = raw_input.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for nested_key in ("name", "id"):
                if value.get(nested_key) is not None:
                    return str(value[nested_key])
    return None


def _tool_input(raw_input: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("tool_input", "input", "arguments"):
        value = raw_input.get(key)
        if isinstance(value, dict):
            return value
    tool = raw_input.get("tool")
    if isinstance(tool, dict):
        for key in ("input", "arguments"):
            value = tool.get(key)
            if isinstance(value, dict):
                return value
    return None


def _tool_output(raw_input: dict[str, Any]) -> Any:
    if "tool_output" in raw_input:
        return raw_input["tool_output"]
    if "output" in raw_input:
        return raw_input["output"]
    return None


def _prompt(raw_input: dict[str, Any]) -> str | None:
    for key in ("prompt", "text", "content"):
        if raw_input.get(key) is not None:
            return str(raw_input[key])
    message = raw_input.get("message")
    if isinstance(message, dict):
        for key in ("text", "content"):
            if message.get(key) is not None:
                return str(message[key])
    return None

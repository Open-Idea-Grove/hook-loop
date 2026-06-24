"""Probe real failure modes when trying to drive opencode with hook-loop.

Run: uv run python experiments/probe_opencode_mismatches.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from hook_loop.codex_adapter import handle_codex_hook, normalize_codex_hook_input
from hook_loop.codex_mapping import SUPPORTED_CODEX_EVENTS, CodexEventMap, MatchSpec, ResolvedRule
from hook_loop.driver import DefaultGuardEvaluator
from hook_loop.dsl import load_loop_spec
from hook_loop.hooks import HookContext
from hook_loop.store import JsonlEventLog


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def load_plan_execute_spec(tmp: Path):
    dsl = Path("examples/plan_execute.json")
    return load_loop_spec(dsl)


def probe_opencode_event_names_not_supported(tmp: Path):
    section("1. opencode event names are not in SUPPORTED_CODEX_EVENTS")
    opencode_events = ["tool.execute.before", "tool.execute.after", "session.idle", "message.updated"]
    print(f"opencode events: {opencode_events}")
    print(f"supported codex events: {sorted(SUPPORTED_CODEX_EVENTS)}")
    overlap = set(opencode_events) & SUPPORTED_CODEX_EVENTS
    print(f"overlap: {overlap if overlap else 'NONE'}")
    # Try normalize with an opencode event name
    try:
        normalize_codex_hook_input("tool.execute.before", {"tool_name": "bash"})
        print("RESULT: normalize accepted opencode event (unexpected)")
    except ValueError as exc:
        print(f"RESULT: normalize raises ValueError: {exc}")


def probe_event_map_resolve_misses_opencode(tmp: Path):
    section("2. codex.event_map.resolve() returns no rules for opencode event names")
    spec = load_plan_execute_spec(tmp)
    # Build a context as if from opencode tool.execute.after
    ctx = HookContext(
        state="executing",
        event=None,
        payload={"tool_output": {"exit_code": 0, "stdout": "ok"}, "prompt": None},
        platform="opencode",
        hook_event_name="tool.execute.after",
        session_id="s1",
        run_id="r1",
        cwd="/repo",
        tool_name="bash",
        tool_input={"command": "uv run pytest -q"},
        raw_input={},
    )
    rules = spec.codex.resolve(ctx) if spec.codex else []
    print(f"rules resolved for hook_event_name='tool.execute.after': {len(rules)}")
    print("=> The PostToolUse rule (which should emit step_done) never fires for opencode.")


def probe_pretool_guardrail_misses_opencode_tool_names(tmp: Path):
    section("3. PreToolUse guardrail misses opencode tool names (lowercase bash/edit/write)")
    spec = load_plan_execute_spec(tmp)
    log = JsonlEventLog(tmp / "events.jsonl")
    # opencode uses lowercase 'bash' and 'write'; codex adapter checks == "Bash" / {"apply_patch","Edit","Write"}
    for tool, cmd in [("bash", "rm -rf .git"), ("write", ".git/config content")]:
        result = handle_codex_hook(
            "PreToolUse",
            {"session_id": "s1", "cwd": "/r", "tool_name": tool, "tool_input": {"command": cmd} if tool == "bash" else {"content": cmd}},
            log,
            spec,
        )
        print(f"  tool_name={tool!r} cmd={cmd!r} -> exit={result.exit_code} stdout={result.stdout!r}")


def probe_plan_complete_guard_not_evaluated(tmp: Path):
    section("4. guard 'plan_complete' has no built-in evaluator")
    ev = DefaultGuardEvaluator()
    print(f"is_satisfied('plan_complete', []) = {ev.is_satisfied('plan_complete', [])}")
    print(f"is_satisfied('evidence_bound_to_criteria', []) = {ev.is_satisfied('evidence_bound_to_criteria', [])}")
    print("=> plan_complete can only be satisfied via guard_satisfied self-declaration in event_map.")


def probe_no_opencode_hook_cli_subcommand(tmp: Path):
    section("5. no 'opencode-hook' CLI subcommand exists")
    proc = subprocess.run(
        ["uv", "run", "hook-loop", "opencode-hook", "--event", "tool.execute.after", "--config", "examples/plan_execute.json", "--event-log", str(tmp / "e.jsonl")],
        input="{}",
        capture_output=True,
        text=True,
    )
    print(f"exit code: {proc.returncode}")
    print(f"stderr: {proc.stderr.strip()[:200]}")


def probe_stop_gate_semantics_mismatch(tmp: Path):
    section("6. opencode has no 'Stop' event; closest is 'session.idle'")
    print("SUPPORTED_CODEX_EVENTS contains 'Stop' but opencode emits 'session.idle'.")
    print("=> The Stop gate (terminal-state check) can never fire for opencode without an event mapping.")


def probe_plugin_is_javascript_not_python(tmp: Path):
    section("7. opencode plugins are JS/TS modules; cannot import hook_loop python package")
    print("opencode plugin contract: export async function returning hooks object (tool.execute.before, event, etc.)")
    print("=> An opencode adapter must shell out to a hook-loop CLI subcommand, which does not exist (see #5).")


def main():
    tmp = Path(tempfile.mkdtemp())
    probe_opencode_event_names_not_supported(tmp)
    probe_event_map_resolve_misses_opencode(tmp)
    probe_pretool_guardrail_misses_opencode_tool_names(tmp)
    probe_plan_complete_guard_not_evaluated(tmp)
    probe_no_opencode_hook_cli_subcommand(tmp)
    probe_stop_gate_semantics_mismatch(tmp)
    probe_plugin_is_javascript_not_python(tmp)
    print("\n=== PROBE COMPLETE ===")


if __name__ == "__main__":
    main()

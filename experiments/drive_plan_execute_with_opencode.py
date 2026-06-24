"""End-to-end experiment: drive the plan_execute loop with opencode events.

This is not a pytest test; it is a runnable experiment that documents whether
the opencode adapter can actually move the state machine to a terminal state.
Run: uv run python experiments/drive_plan_execute_with_opencode.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from hook_loop.dsl import load_loop_spec
from hook_loop.opencode_adapter import handle_opencode_hook
from hook_loop.store import JsonlEventLog


def main() -> None:
    spec = load_loop_spec("examples/plan_execute.json")
    tmp = Path(tempfile.mkdtemp())
    log = JsonlEventLog(tmp / "events.jsonl")
    session = {"session_id": "s1", "cwd": "/repo"}

    def fire(event: str, payload: dict) -> int:
        r = handle_opencode_hook(event, {**session, **payload}, log, spec)
        transitions = [e for e in log.read_all() if e.event_type == "state_transitioned"]
        state = transitions[-1].payload["to"] if transitions else spec.definition.initial_state
        print(f"  {event:24s} -> exit={r.exit_code} verdict={r.stdout[:60]!r} state={state}")
        return r.exit_code

    print("=== Driving plan_execute with opencode events ===")
    # 1. kickoff: user message (non-verdict) -> backlog -> planning
    fire("message.updated", {"text": "implement opencode adapter for hook-loop"})
    # 2. plan ready: user message containing 'plan ready'
    fire("message.updated", {"text": "plan ready: 3 steps"})
    # 3. step done: tool.execute.after with bash test passing
    fire(
        "tool.execute.after",
        {"tool": "bash", "input": {"command": "uv run pytest -q"}, "output": {"exit_code": 0, "stdout": "89 passed"}},
    )
    # 4. all steps pass: user message
    fire("message.updated", {"text": "all steps pass, plan complete"})
    # 5. stop: session.idle
    print("  --- session.idle (Stop gate) ---")
    stop = handle_opencode_hook("session.idle", session, log, spec)
    print(f"  session.idle            -> exit={stop.exit_code} stdout={stop.stdout!r}")

    print("\n=== Final state machine trace ===")
    for e in log.read_all():
        if e.event_type == "state_transitioned":
            print(f"  {e.payload['from']} --{e.payload['event']}--> {e.payload['to']}")
        elif e.event_type in ("transition_rejected", "stop_contract_failed"):
            print(f"  [{e.event_type}] {e.payload.get('reason') or e.payload.get('message','')}")

    transitions = [e for e in log.read_all() if e.event_type == "state_transitioned"]
    final = transitions[-1].payload["to"] if transitions else spec.definition.initial_state
    print(f"\nFINAL STATE: {final}")
    print(f"REACHED TERMINAL (done): {final == 'done'}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hook_loop.dsl import DslError, load_loop_spec
from hook_loop.evaluator import FakeEvaluator
from hook_loop.runtime import FakeAgent, LoopRuntime
from hook_loop.store import JsonlEventLog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hook-loop")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate a hook loop JSON DSL file")
    validate.add_argument("path", type=Path)

    simulate = subparsers.add_parser("simulate", help="run a deterministic hook loop simulation")
    simulate.add_argument("path", type=Path)
    simulate.add_argument("--event-log", type=Path, default=Path("hook-loop-events.jsonl"))
    simulate.add_argument("--session-id", default="session-1")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.path)
    if args.command == "simulate":
        return _simulate(args.path, args.event_log, args.session_id)
    parser.error(f"unknown command: {args.command}")
    return 2


def _validate(path: Path) -> int:
    try:
        spec = load_loop_spec(path)
    except DslError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    print(f"valid: {spec.definition.id}")
    return 0


def _simulate(path: Path, event_log: Path, session_id: str) -> int:
    try:
        spec = load_loop_spec(path)
    except DslError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    try:
        runtime = LoopRuntime(
            definition=spec.definition,
            store=JsonlEventLog(event_log),
            agent=FakeAgent({state: list(steps) for state, steps in spec.simulation.agent_steps.items()}),
            evaluator=FakeEvaluator(list(spec.simulation.verdicts)),
            session_id=session_id,
        )
        final_state = runtime.run_until_stop(spec.simulation.budget)
    except RuntimeError as exc:
        print(f"simulation failed: {exc}", file=sys.stderr)
        return 1
    print(f"final_state: {final_state}")
    print(f"event_log: {event_log}")
    return 0 if final_state in spec.definition.terminal_states else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hook_loop.codex_adapter import handle_codex_hook
from hook_loop.codex_scaffold import install_codex_scaffold
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

    codex_hook = subparsers.add_parser("codex-hook", help="run a Codex lifecycle hook adapter")
    codex_hook.add_argument("--event", required=True)
    codex_hook.add_argument("--config", type=Path, required=True)
    codex_hook.add_argument("--event-log", type=Path, required=True)

    codex = subparsers.add_parser("codex", help="Codex hook-loop helpers")
    codex_subparsers = codex.add_subparsers(dest="codex_command", required=True)
    codex_install = codex_subparsers.add_parser("install", help="install Codex hook scaffold")
    codex_install.add_argument("--profile", default="software_delivery")
    codex_install.add_argument("--target", choices=["project", "user", "directory"], default="directory")
    codex_install.add_argument("--destination", type=Path, default=Path("."))
    codex_install.add_argument("--dry-run", action="store_true")
    codex_install.add_argument("--write", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.path)
    if args.command == "simulate":
        return _simulate(args.path, args.event_log, args.session_id)
    if args.command == "codex-hook":
        return _codex_hook(args.event, args.config, args.event_log)
    if args.command == "codex" and args.codex_command == "install":
        return _codex_install(args.profile, args.target, args.destination, not args.write or args.dry_run)
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


def _codex_hook(event_name: str, config_path: Path, event_log: Path) -> int:
    try:
        load_loop_spec(config_path)
    except DslError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    try:
        raw_input = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        print(f"invalid hook input: {exc.msg}", file=sys.stderr)
        return 1
    result = handle_codex_hook(event_name, raw_input, JsonlEventLog(event_log))
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.exit_code


def _codex_install(profile: str, target: str, destination: Path, dry_run: bool) -> int:
    try:
        result = install_codex_scaffold(profile=profile, target=target, destination=destination, dry_run=dry_run)
    except ValueError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    label = "planned" if dry_run else "written"
    paths = result.planned if dry_run else result.written
    print(f"{label}:")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hook_loop.dsl import DslError, load_loop_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hook-loop")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate a hook loop JSON DSL file")
    validate.add_argument("path", type=Path)

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.path)
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


if __name__ == "__main__":
    raise SystemExit(main())

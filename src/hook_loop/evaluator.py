from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Verdict:
    status: str
    details: str


def parse_verdict(text: str) -> Verdict:
    lines = text.splitlines()
    first = lines[0].strip() if lines else ""
    if first not in {"PASS", "NEEDS_WORK"}:
        raise ValueError("verdict must start with PASS or NEEDS_WORK")
    return Verdict(status=first, details="\n".join(lines[1:]).strip())


class FakeEvaluator:
    def __init__(self, verdicts: list[Verdict]):
        self._verdicts = list(verdicts)

    def evaluate(self, context: dict[str, Any]) -> Verdict:
        if not self._verdicts:
            raise RuntimeError("FakeEvaluator has no remaining verdicts")
        return self._verdicts.pop(0)

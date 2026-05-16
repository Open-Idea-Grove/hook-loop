from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class HookContext:
    state: str
    event: str | None
    payload: dict


@dataclass(frozen=True)
class HookDecision:
    allowed: bool
    messages: list[str] = field(default_factory=list)

    @classmethod
    def allow(cls, message: str | None = None) -> "HookDecision":
        return cls(True, [] if message is None else [message])

    @classmethod
    def block(cls, reason: str) -> "HookDecision":
        return cls(False, [reason])


HookFn = Callable[[HookContext], HookDecision]


class HookBus:
    def __init__(self) -> None:
        self._hooks: dict[str, list[HookFn]] = defaultdict(list)

    def register(self, stage: str, hook: HookFn) -> None:
        self._hooks[stage].append(hook)

    def fire(self, stage: str, context: HookContext) -> HookDecision:
        allowed = True
        messages: list[str] = []
        for hook in self._hooks.get(stage, []):
            decision = hook(context)
            allowed = allowed and decision.allowed
            messages.extend(decision.messages)
        return HookDecision(allowed=allowed, messages=messages)

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class HookContext:
    state: str
    event: str | None
    payload: dict
    platform: str | None = None
    hook_event_name: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    cwd: str | None = None
    tool_name: str | None = None
    tool_input: dict | None = None
    raw_input: dict | None = None


@dataclass(frozen=True)
class HookDecision:
    verdict: str
    messages: list[str] = field(default_factory=list)
    patch: dict | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict in {"allow", "steer", "redact"}

    @classmethod
    def allow(cls, message: str | None = None) -> "HookDecision":
        return cls("allow", [] if message is None else [message])

    @classmethod
    def block(cls, reason: str) -> "HookDecision":
        return cls("block", [reason])

    @classmethod
    def steer(cls, message: str) -> "HookDecision":
        return cls("steer", [message])

    @classmethod
    def pause(cls, reason: str) -> "HookDecision":
        return cls("pause", [reason])

    @classmethod
    def replan(cls, reason: str) -> "HookDecision":
        return cls("replan", [reason])

    @classmethod
    def redact(cls, message: str, patch: dict | None = None) -> "HookDecision":
        return cls("redact", [message], patch)


HookFn = Callable[[HookContext], HookDecision]


class HookBus:
    def __init__(self) -> None:
        self._hooks: dict[str, list[HookFn]] = defaultdict(list)

    def register(self, stage: str, hook: HookFn) -> None:
        self._hooks[stage].append(hook)

    def fire(self, stage: str, context: HookContext) -> HookDecision:
        verdict = "allow"
        messages: list[str] = []
        patch: dict | None = None
        for hook in self._hooks.get(stage, []):
            decision = hook(context)
            if verdict == "allow" and decision.verdict != "allow":
                verdict = decision.verdict
            elif decision.verdict in {"block", "pause", "replan"}:
                verdict = decision.verdict
            if decision.patch is not None:
                patch = decision.patch
            messages.extend(decision.messages)
        return HookDecision(verdict=verdict, messages=messages, patch=patch)

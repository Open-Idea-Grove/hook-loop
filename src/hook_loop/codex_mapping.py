from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from hook_loop.hooks import HookContext


SUPPORTED_CODEX_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "Stop",
    "PreCompact",
    "PostCompact",
}


@dataclass(frozen=True)
class MatchSpec:
    """Conditions under which a codex event_map rule fires.

    All specified conditions must match (logical AND). An empty MatchSpec always
    matches. Regex conditions use `re.search`.
    """

    tool_name: str | None = None
    command_match: str | None = None
    prompt_match: str | None = None
    prompt_not_match: str | None = None
    exit_code: int | str | None = None

    def matches(self, context: HookContext) -> bool:
        if self.tool_name is not None and (context.tool_name or "") != self.tool_name:
            return False
        command = str((context.tool_input or {}).get("command", ""))
        if self.command_match is not None and not re.search(self.command_match, command):
            return False
        prompt = str(context.payload.get("prompt") or "")
        if self.prompt_match is not None and not re.search(self.prompt_match, prompt):
            return False
        if self.prompt_not_match is not None and re.search(self.prompt_not_match, prompt):
            return False
        if self.exit_code is not None:
            output = context.payload.get("tool_output") or {}
            if not isinstance(output, dict):
                output = {}
            if str(output.get("exit_code")) != str(self.exit_code):
                return False
        return True


@dataclass(frozen=True)
class RecordSpec:
    """A side-effect event to append before emitting a transition event."""

    event_type: str
    actor: str
    payload: dict[str, Any] = field(default_factory=dict)
    include: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResolvedRule:
    codex_event: str
    when: MatchSpec
    emit: str
    record: RecordSpec | None
    guard_satisfied: frozenset[str]


@dataclass(frozen=True)
class CodexEventMap:
    rules: tuple[ResolvedRule, ...]

    def resolve(self, context: HookContext) -> list[ResolvedRule]:
        return [
            rule
            for rule in self.rules
            if rule.codex_event == context.hook_event_name and rule.when.matches(context)
        ]

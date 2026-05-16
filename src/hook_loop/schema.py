from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class SchemaError(ValueError):
    """Raised when a loop definition is invalid."""


@dataclass(frozen=True)
class Transition:
    from_state: str
    event: str
    to_state: str
    guards: tuple[str, ...] = field(default_factory=tuple)
    actions: tuple[str, ...] = field(default_factory=tuple)
    resume_policy: str | None = None


@dataclass(frozen=True)
class LoopDefinition:
    id: str
    initial_state: str
    states: tuple[str, ...]
    events: tuple[str, ...]
    transitions: tuple[Transition, ...]
    terminal_states: tuple[str, ...]
    stop_state: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LoopDefinition":
        loop_id = _required_str(raw, "id")
        initial_state = _required_str(raw, "initial_state")
        states = tuple(_required_str_list(raw, "states"))
        events = tuple(_required_str_list(raw, "events"))
        default_terminal_states = [state for state in ("done", "stopped") if state in states]
        terminal_states = tuple(raw.get("terminal_states", default_terminal_states))
        _reject_duplicates(states, "state")
        _reject_duplicates(events, "event")
        if not terminal_states or not all(isinstance(item, str) and item for item in terminal_states):
            raise SchemaError("terminal_states must be a non-empty list of strings")
        _reject_duplicates(terminal_states, "terminal state")

        if initial_state not in states:
            raise SchemaError(f"initial_state references unknown state: {initial_state}")
        for terminal_state in terminal_states:
            if terminal_state not in states:
                raise SchemaError(f"terminal state references unknown state: {terminal_state}")
        stop_state = raw.get("stop_state")
        if stop_state is None and "stopped" in terminal_states:
            stop_state = "stopped"
        if stop_state is not None:
            if not isinstance(stop_state, str) or not stop_state:
                raise SchemaError("stop_state must be a non-empty string")
            if stop_state not in terminal_states:
                raise SchemaError(f"stop_state must reference a terminal state: {stop_state}")

        transitions = tuple(_transition_from_dict(item) for item in raw.get("transitions", []))
        transition_keys: set[tuple[str, str]] = set()
        for transition in transitions:
            if transition.from_state not in states:
                raise SchemaError(f"transition references unknown state: {transition.from_state}")
            if transition.to_state not in states:
                raise SchemaError(f"transition references unknown state: {transition.to_state}")
            if transition.event not in events:
                raise SchemaError(f"transition references unknown event: {transition.event}")
            transition_key = (transition.from_state, transition.event)
            if transition_key in transition_keys:
                raise SchemaError(f"duplicate transition: {transition.from_state}/{transition.event}")
            transition_keys.add(transition_key)

        return cls(
            id=loop_id,
            initial_state=initial_state,
            states=states,
            events=events,
            transitions=transitions,
            terminal_states=terminal_states,
            stop_state=stop_state,
        )

    def transition_for(self, state: str, event: str) -> Transition:
        for transition in self.transitions:
            if transition.from_state == state and transition.event == event:
                return transition
        raise KeyError((state, event))


def _transition_from_dict(raw: dict[str, Any]) -> Transition:
    return Transition(
        from_state=_required_str(raw, "from"),
        event=_required_str(raw, "event"),
        to_state=_required_str(raw, "to"),
        guards=tuple(_optional_str_list(raw, "guards")),
        actions=tuple(_optional_str_list(raw, "actions")),
        resume_policy=_optional_str(raw, "resume_policy"),
    )


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise SchemaError(f"{key} must be a non-empty string")
    return value


def _required_str_list(raw: dict[str, Any], key: str) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SchemaError(f"{key} must be a list of non-empty strings")
    return value


def _optional_str(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise SchemaError(f"{key} must be a non-empty string")
    return value


def _optional_str_list(raw: dict[str, Any], key: str) -> list[str]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SchemaError(f"{key} must be a list of non-empty strings")
    return value


def _reject_duplicates(values: tuple[str, ...], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise SchemaError(f"duplicate {label}: {value}")
        seen.add(value)

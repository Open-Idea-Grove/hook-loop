from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from hook_loop.events import Event, new_event
from hook_loop.schema import LoopDefinition
from hook_loop.state_machine import StateMachine, TransitionRejected
from hook_loop.store import JsonlEventLog, recover_current_state


@dataclass(frozen=True)
class ApplyResult:
    applied: bool
    rejected: bool = False
    from_state: str | None = None
    to_state: str | None = None
    reason: str | None = None


class GuardEvaluator:
    """Evaluates whether a named guard is satisfied by the session event log."""

    def is_satisfied(self, guard: str, events: list[Event]) -> bool:
        raise NotImplementedError


class DefaultGuardEvaluator(GuardEvaluator):
    """Built-in guard semantics for the software_delivery profile.

    `evidence_bound_to_criteria` is satisfied when the session has at least one
    `evidence_registered` event. Unknown guards are not satisfied.
    """

    def is_satisfied(self, guard: str, events: list[Event]) -> bool:
        if guard == "evidence_bound_to_criteria":
            return any(event.event_type == "evidence_registered" for event in events)
        return False


class EventSourcedLoopDriver:
    """Drives a loop definition one event at a time against an append-only event log.

    Unlike `LoopRuntime`, this driver does not own a fake agent or evaluator:
    external callers (such as a Codex hook adapter) decide which transition event
    to emit and when. The driver only resolves guards, applies the transition
    through the state machine, and records the result. A rejected transition is
    recorded but does not move the loop to the stop state, so a real conversation
    is not killed by a single out-of-order event.
    """

    def __init__(
        self,
        definition: LoopDefinition,
        store: JsonlEventLog,
        session_id: str,
        guard_evaluator: GuardEvaluator | None = None,
    ):
        self.definition = definition
        self.store = store
        self.session_id = session_id
        self.machine = StateMachine(definition)
        self.guard_evaluator = guard_evaluator or DefaultGuardEvaluator()
        self.run_id = str(uuid4())
        self.current_state = recover_current_state(self._session_events()) or definition.initial_state

    def is_terminal(self) -> bool:
        return self.current_state in self.definition.terminal_states

    def apply_event(
        self,
        event: str,
        payload: dict[str, Any],
        explicit_guards: set[str] | None = None,
    ) -> ApplyResult:
        explicit_guards = explicit_guards or set()
        from_state = self.current_state
        try:
            transition = self.machine.transition_for(from_state, event)
        except TransitionRejected as exc:
            self._record_rejected(event, payload, from_state, str(exc))
            return ApplyResult(applied=False, rejected=True, from_state=from_state, to_state=from_state, reason=str(exc))

        satisfied = self._satisfied_guards(transition.guards, explicit_guards)
        missing = set(transition.guards) - satisfied
        if missing:
            names = ", ".join(sorted(missing))
            reason = f"Missing guards for transition: {names}"
            self._record_rejected(event, payload, from_state, reason)
            return ApplyResult(applied=False, rejected=True, from_state=from_state, to_state=from_state, reason=reason)

        self.current_state = transition.to_state
        self._append(
            "state_transitioned",
            "driver",
            {"from": from_state, "event": event, "to": transition.to_state, **payload},
        )
        return ApplyResult(
            applied=True,
            rejected=False,
            from_state=from_state,
            to_state=transition.to_state,
        )

    def _satisfied_guards(self, guards: tuple[str, ...], explicit_guards: set[str]) -> set[str]:
        events = self._session_events()
        satisfied = set(explicit_guards)
        for guard in guards:
            if self.guard_evaluator.is_satisfied(guard, events):
                satisfied.add(guard)
        return satisfied

    def _record_rejected(self, event: str, payload: dict[str, Any], from_state: str, reason: str) -> None:
        self._append(
            "transition_rejected",
            "driver",
            {"from": from_state, "event": event, "reason": reason, **payload},
        )

    def _session_events(self) -> list[Event]:
        return [event for event in self.store.read_all() if event.session_id == self.session_id]

    def _append(self, event_type: str, actor: str, payload: dict[str, Any]) -> None:
        self.store.append(
            new_event(
                session_id=self.session_id,
                run_id=self.run_id,
                state=self.current_state,
                event_type=event_type,
                actor=actor,
                payload=payload,
            )
        )

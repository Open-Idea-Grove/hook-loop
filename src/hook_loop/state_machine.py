from __future__ import annotations

from dataclasses import dataclass

from hook_loop.schema import LoopDefinition, Transition


class TransitionRejected(ValueError):
    """Raised when an event cannot transition the current state."""


@dataclass(frozen=True)
class StateMachine:
    definition: LoopDefinition

    def transition_for(self, state: str, event: str) -> Transition:
        try:
            return self.definition.transition_for(state, event)
        except KeyError as exc:
            raise TransitionRejected(f"No transition for state={state!r}, event={event!r}") from exc

    def apply(self, state: str, event: str, satisfied_guards: set[str]) -> str:
        transition = self.transition_for(state, event)
        missing = set(transition.guards) - satisfied_guards
        if missing:
            names = ", ".join(sorted(missing))
            raise TransitionRejected(f"Missing guards for transition: {names}")
        return transition.to_state

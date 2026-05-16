from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from hook_loop.evaluator import FakeEvaluator
from hook_loop.events import Event, new_event
from hook_loop.hooks import HookBus, HookContext
from hook_loop.schema import LoopDefinition
from hook_loop.state_machine import StateMachine, TransitionRejected
from hook_loop.store import JsonlEventLog, recover_current_state


@dataclass(frozen=True)
class AgentStep:
    event: str
    payload: dict[str, Any] = field(default_factory=dict)


class FakeAgent:
    def __init__(self, steps_by_state: dict[str, list[AgentStep]]):
        self._steps_by_state = {state: list(steps) for state, steps in steps_by_state.items()}

    def next_steps(self, state: str) -> list[AgentStep]:
        steps = self._steps_by_state.get(state, [])
        if not steps:
            return []
        return [steps.pop(0)]


@dataclass(frozen=True)
class RuntimeBudget:
    max_turns: int
    max_no_progress_turns: int = 2


class LoopRuntime:
    def __init__(
        self,
        definition: LoopDefinition,
        store: JsonlEventLog,
        agent: FakeAgent,
        evaluator: FakeEvaluator,
        hooks: HookBus | None = None,
        session_id: str = "session-1",
    ):
        self.definition = definition
        self.store = store
        self.agent = agent
        self.evaluator = evaluator
        self.hooks = hooks or HookBus()
        self.session_id = session_id
        self.machine = StateMachine(definition)
        self.run_id = str(uuid4())
        self.current_state = recover_current_state(self._session_events()) or definition.initial_state

    def run_until_stop(self, budget: RuntimeBudget) -> str:
        if not self._session_events():
            self._append("session_initialized", "runtime", {"initial_state": self.current_state})

        no_progress_turns = 0
        for _ in range(budget.max_turns):
            if self._is_terminal():
                return self.current_state

            before = self.hooks.fire("before_turn", HookContext(self.current_state, None, {}))
            if not before.allowed:
                return self._stop("transition_blocked", {"messages": before.messages})

            progressed = False
            if self.current_state == "evaluating":
                progressed = self._evaluate() or progressed
            else:
                for step in self.agent.next_steps(self.current_state):
                    progressed = self._apply_step(step) or progressed
                    if self._is_terminal():
                        return self.current_state
                    if self.current_state == "evaluating":
                        progressed = self._evaluate() or progressed
                    if self._is_terminal():
                        return self.current_state

            if self._is_terminal():
                return self.current_state

            if progressed:
                no_progress_turns = 0
            else:
                no_progress_turns += 1
                if no_progress_turns >= budget.max_no_progress_turns:
                    return self._stop("budget_exhausted", {"reason": "no productive event"})

        if self._is_terminal():
            return self.current_state
        return self._stop("budget_exhausted", {"reason": "max_turns"})

    def _evaluate(self) -> bool:
        verdict = self.evaluator.evaluate({"state": self.current_state})
        self._append("verdict_recorded", "evaluator", {"status": verdict.status, "details": verdict.details})
        event = "evaluator_passed" if verdict.status == "PASS" else "evaluator_failed"
        guards = {"evidence_bound_to_criteria"} if verdict.status == "PASS" else set()
        return self._transition(event, {"verdict": verdict.status}, guards)

    def _apply_step(self, step: AgentStep) -> bool:
        if step.event == "evidence_recorded":
            self._append("evidence_registered", "agent", step.payload)
        return self._transition(step.event, step.payload, set())

    def _transition(self, event: str, payload: dict[str, Any], guards: set[str]) -> bool:
        decision = self.hooks.fire(
            "before_state_transition",
            HookContext(self.current_state, event, payload),
        )
        if not decision.allowed:
            self._stop("transition_blocked", {"messages": decision.messages})
            return False

        try:
            next_state = self.machine.apply(self.current_state, event, guards)
        except TransitionRejected as exc:
            self._stop("transition_rejected", {"reason": str(exc), "event": event})
            return False

        previous = self.current_state
        self.current_state = next_state
        self._append(
            "state_transitioned",
            "runtime",
            {"from": previous, "event": event, "to": next_state, **payload},
        )
        return True

    def _stop(self, event_type: str, payload: dict[str, Any]) -> str:
        self.current_state = "stopped"
        self._append(event_type, "runtime", payload)
        return self.current_state

    def _is_terminal(self) -> bool:
        return self.current_state in {"done", "stopped"}

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

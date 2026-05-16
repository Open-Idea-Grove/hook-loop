from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from hook_loop.evaluator import Verdict
from hook_loop.runtime import AgentStep, RuntimeBudget
from hook_loop.schema import LoopDefinition, SchemaError


class DslError(ValueError):
    """Raised when a JSON loop DSL file is invalid."""


@dataclass(frozen=True)
class SimulationSpec:
    budget: RuntimeBudget = field(default_factory=lambda: RuntimeBudget(max_turns=10))
    agent_steps: dict[str, tuple[AgentStep, ...]] = field(default_factory=dict)
    verdicts: tuple[Verdict, ...] = ()


@dataclass(frozen=True)
class LoopSpec:
    definition: LoopDefinition
    simulation: SimulationSpec = field(default_factory=SimulationSpec)


def load_loop_spec(path: Path | str) -> LoopSpec:
    raw = _load_json(path)
    if not isinstance(raw, dict):
        raise DslError("top-level DSL document must be an object")
    loop_raw = raw.get("loop")
    if not isinstance(loop_raw, dict):
        raise DslError("DSL document must contain a loop object")
    if "stop_state" not in loop_raw:
        raise DslError("loop.stop_state is required for DSL simulation")
    try:
        definition = LoopDefinition.from_dict(loop_raw)
    except SchemaError as exc:
        raise DslError(str(exc)) from exc
    simulation = _parse_simulation(raw.get("simulation", {}))
    _validate_loop_spec(definition, simulation)
    return LoopSpec(definition=definition, simulation=simulation)


def _load_json(path: Path | str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise DslError(f"invalid JSON: {exc.msg}") from exc
    except OSError as exc:
        raise DslError(f"cannot read DSL file: {exc}") from exc


def _parse_simulation(raw: Any) -> SimulationSpec:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise DslError("simulation must be an object")
    return SimulationSpec(
        budget=_parse_budget(raw.get("budget", {})),
        agent_steps=_parse_agent_steps(raw.get("agent_steps", {})),
        verdicts=_parse_verdicts(raw.get("verdicts", [])),
    )


def _parse_budget(raw: Any) -> RuntimeBudget:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise DslError("simulation.budget must be an object")
    return RuntimeBudget(
        max_turns=_positive_int(raw.get("max_turns", 10), "simulation.budget.max_turns"),
        max_no_progress_turns=_positive_int(
            raw.get("max_no_progress_turns", 2),
            "simulation.budget.max_no_progress_turns",
        ),
    )


def _parse_agent_steps(raw: Any) -> dict[str, tuple[AgentStep, ...]]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise DslError("simulation.agent_steps must be an object")
    parsed: dict[str, tuple[AgentStep, ...]] = {}
    for state, steps in raw.items():
        if not isinstance(state, str) or not state:
            raise DslError("simulation.agent_steps keys must be non-empty strings")
        if not isinstance(steps, list):
            raise DslError(f"simulation.agent_steps.{state} must be a list")
        parsed[state] = tuple(_parse_agent_step(step, state) for step in steps)
    return parsed


def _parse_agent_step(raw: Any, state: str) -> AgentStep:
    if not isinstance(raw, dict):
        raise DslError(f"simulation.agent_steps.{state} entries must be objects")
    event = raw.get("event")
    if not isinstance(event, str) or not event:
        raise DslError(f"simulation.agent_steps.{state}.event must be a non-empty string")
    payload = raw.get("payload", {})
    if not isinstance(payload, dict):
        raise DslError(f"simulation.agent_steps.{state}.payload must be an object")
    return AgentStep(event=event, payload=payload)


def _parse_verdicts(raw: Any) -> tuple[Verdict, ...]:
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise DslError("simulation.verdicts must be a list")
    verdicts: list[Verdict] = []
    for item in raw:
        if not isinstance(item, dict):
            raise DslError("simulation.verdicts entries must be objects")
        status = item.get("status")
        details = item.get("details", "")
        if status not in {"PASS", "NEEDS_WORK"}:
            raise DslError("simulation.verdicts.status must be PASS or NEEDS_WORK")
        if not isinstance(details, str):
            raise DslError("simulation.verdicts.details must be a string")
        verdicts.append(Verdict(status=status, details=details))
    return tuple(verdicts)


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or value < 1:
        raise DslError(f"{name} must be a positive integer")
    return value


def _validate_loop_spec(definition: LoopDefinition, simulation: SimulationSpec) -> None:
    if definition.stop_state is None:
        raise DslError("loop.stop_state is required for DSL simulation")
    for state, steps in simulation.agent_steps.items():
        if state not in definition.states:
            raise DslError(f"simulation.agent_steps references unknown state: {state}")
        for step in steps:
            if step.event not in definition.events:
                raise DslError(f"simulation agent step references unknown event: {step.event}")
            try:
                definition.transition_for(state, step.event)
            except KeyError as exc:
                raise DslError(f"No transition for simulation step: {state}/{step.event}") from exc

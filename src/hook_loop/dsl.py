from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from hook_loop.codex_mapping import (
    SUPPORTED_CODEX_EVENTS,
    CodexEventMap,
    MatchSpec,
    RecordSpec,
    ResolvedRule,
)
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
    codex: CodexEventMap | None = None


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
    codex = _parse_codex(raw.get("codex"))
    _validate_loop_spec(definition, simulation)
    if codex is not None:
        _validate_codex_mapping(definition, codex)
    return LoopSpec(definition=definition, simulation=simulation, codex=codex)


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


def _parse_codex(raw: Any) -> CodexEventMap | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DslError("codex must be an object")
    event_map = raw.get("event_map", [])
    if not isinstance(event_map, list):
        raise DslError("codex.event_map must be a list")
    rules: list[ResolvedRule] = []
    for index, rule_raw in enumerate(event_map):
        rules.append(_parse_codex_rule(rule_raw, index))
    return CodexEventMap(rules=tuple(rules))


def _parse_codex_rule(raw: Any, index: int) -> ResolvedRule:
    if not isinstance(raw, dict):
        raise DslError(f"codex.event_map[{index}] must be an object")
    codex_event = raw.get("codex_event")
    if not isinstance(codex_event, str) or not codex_event:
        raise DslError(f"codex.event_map[{index}].codex_event must be a non-empty string")
    if codex_event not in SUPPORTED_CODEX_EVENTS:
        raise DslError(
            f"codex.event_map[{index}].codex_event is not a supported Codex hook event: {codex_event}"
        )
    emit = raw.get("emit")
    if not isinstance(emit, str) or not emit:
        raise DslError(f"codex.event_map[{index}].emit must be a non-empty string")
    when = _parse_match_spec(raw.get("when"), index)
    record = _parse_record_spec(raw.get("record"), index)
    guard_satisfied = _parse_guard_satisfied(raw.get("guard_satisfied"), index)
    return ResolvedRule(
        codex_event=codex_event,
        when=when,
        emit=emit,
        record=record,
        guard_satisfied=guard_satisfied,
    )


def _parse_match_spec(raw: Any, index: int) -> MatchSpec:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise DslError(f"codex.event_map[{index}].when must be an object")
    tool_name = raw.get("tool_name")
    if tool_name is not None and not (isinstance(tool_name, str) and tool_name):
        raise DslError(f"codex.event_map[{index}].when.tool_name must be a non-empty string")
    for regex_key in ("command_match", "prompt_match", "prompt_not_match"):
        value = raw.get(regex_key)
        if value is not None and not isinstance(value, str):
            raise DslError(f"codex.event_map[{index}].when.{regex_key} must be a string")
    exit_code = raw.get("exit_code")
    if exit_code is not None and not isinstance(exit_code, (int, str)):
        raise DslError(f"codex.event_map[{index}].when.exit_code must be an int or string")
    return MatchSpec(
        tool_name=tool_name,
        command_match=raw.get("command_match"),
        prompt_match=raw.get("prompt_match"),
        prompt_not_match=raw.get("prompt_not_match"),
        exit_code=exit_code,
    )


def _parse_record_spec(raw: Any, index: int) -> RecordSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DslError(f"codex.event_map[{index}].record must be an object")
    event_type = raw.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        raise DslError(f"codex.event_map[{index}].record.event_type must be a non-empty string")
    actor = raw.get("actor")
    if not isinstance(actor, str) or not actor:
        raise DslError(f"codex.event_map[{index}].record.actor must be a non-empty string")
    payload = raw.get("payload", {})
    if not isinstance(payload, dict):
        raise DslError(f"codex.event_map[{index}].record.payload must be an object")
    include = raw.get("include", [])
    if not isinstance(include, list) or not all(isinstance(item, str) and item for item in include):
        raise DslError(f"codex.event_map[{index}].record.include must be a list of non-empty strings")
    return RecordSpec(event_type=event_type, actor=actor, payload=dict(payload), include=tuple(include))


def _parse_guard_satisfied(raw: Any, index: int) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise DslError(f"codex.event_map[{index}].guard_satisfied must be a list of non-empty strings")
    return frozenset(raw)


def _validate_codex_mapping(definition: LoopDefinition, codex: CodexEventMap) -> None:
    events_with_transitions = {transition.event for transition in definition.transitions}
    for rule in codex.rules:
        if rule.emit not in definition.events:
            raise DslError(f"codex.event_map emit references unknown event: {rule.emit}")
        if rule.emit not in events_with_transitions:
            raise DslError(f"codex.event_map emit has no matching transition: {rule.emit}")

# Hook Loop Runtime Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the B-stage minimal hook loop runtime: a platform-neutral state machine, append-only event log, hook bus, fake evaluator, and loop simulation tests.

**Architecture:** Implement a small Python package under `src/hook_loop/` using explicit dataclasses and standard-library JSON/JSONL persistence. Keep the B-stage runtime separate from the later C-stage generator: schemas are hand-written Python dicts or JSON fixtures, not generated.

**Tech Stack:** Python 3.11+, standard library, pytest via `uv run pytest`.

---

## Constraints

- Implement B-stage only. Do not implement the C-stage DSL generator.
- Do not add platform adapters for Codex, Claude Code, or pi in this plan.
- Do not stage or modify unrelated worktree changes such as `.gitignore` or `docs/research/**`.
- Keep each module focused and small enough to understand independently.
- Prefer TDD: write the failing test, run it, implement the smallest code, run it again, then commit.

## Constitution Check

- **State-machine-first**: PASS. Tasks 2 and 6 define explicit states, events, guards,
  transitions, and stop behavior before runtime behavior is implemented.
- **Platform-neutral core**: PASS. The plan implements only in-process runtime primitives;
  platform adapters and the C-stage generator are explicitly out of scope.
- **Evidence and recovery**: PASS. Task 3 implements append-only JSONL recovery; Task 6
  records evidence and evaluator verdict events during loop simulation.
- **Test-first runtime semantics**: PASS. Every task starts with a failing pytest test,
  expected failure, minimal implementation, passing verification, and commit step.
- **Python uses uv**: PASS. The plan uses `uv run pytest` for tests and declares pytest
  in the `dev` dependency group for uv-managed environments.

## File Structure

- Create `pyproject.toml`: package metadata and pytest config for `src` layout.
- Create `src/hook_loop/__init__.py`: public package exports and version.
- Create `src/hook_loop/schema.py`: `LoopDefinition`, `Transition`, schema loading and validation.
- Create `src/hook_loop/state_machine.py`: legal transition lookup and guard-aware state transition.
- Create `src/hook_loop/events.py`: event dataclass and event factory helpers.
- Create `src/hook_loop/store.py`: append-only JSONL event log and recovery helpers.
- Create `src/hook_loop/hooks.py`: in-process hook bus and allow/block decisions.
- Create `src/hook_loop/evaluator.py`: machine-readable evaluator verdict parsing and fake evaluator.
- Create `src/hook_loop/runtime.py`: minimal turn runner that wires state machine, store, hooks, and fake evaluator.
- Create `tests/test_package_import.py`: package smoke test.
- Create `tests/test_state_machine.py`: state machine and schema contract tests.
- Create `tests/test_event_store.py`: JSONL persistence and recovery tests.
- Create `tests/test_hooks.py`: hook bus contract tests.
- Create `tests/test_evaluator.py`: verdict parser and fake evaluator tests.
- Create `tests/test_runtime_simulation.py`: complete loop simulation tests.

## Chunk 1: Core State And Persistence

### Task 1: Python Package Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/hook_loop/__init__.py`
- Create: `tests/test_package_import.py`

- [ ] **Step 1: Write the failing import test**

Create `tests/test_package_import.py`:

```python
def test_package_imports():
    import hook_loop

    assert hook_loop.__version__ == "0.1.0"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run --with pytest pytest tests/test_package_import.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'hook_loop'`.

- [ ] **Step 3: Add minimal package scaffold**

Create `pyproject.toml`:

```toml
[project]
name = "hook-loop"
version = "0.1.0"
description = "Platform-neutral hook loop runtime experiments"
requires-python = ">=3.11"
dependencies = []

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

Create `src/hook_loop/__init__.py`:

```python
"""Platform-neutral hook loop runtime."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `uv run pytest tests/test_package_import.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/hook_loop/__init__.py tests/test_package_import.py
git commit -m "chore: scaffold hook loop python package"
```

### Task 2: Schema And State Machine Contracts

**Files:**
- Create: `src/hook_loop/schema.py`
- Create: `src/hook_loop/state_machine.py`
- Create: `tests/test_state_machine.py`

- [ ] **Step 1: Write failing state machine tests**

Create `tests/test_state_machine.py`:

```python
import pytest

from hook_loop.schema import LoopDefinition, SchemaError
from hook_loop.state_machine import StateMachine, TransitionRejected


def delivery_schema():
    return {
        "id": "software_delivery",
        "initial_state": "backlog",
        "states": ["backlog", "building", "evidence_ready", "evaluating", "needs_work", "done"],
        "events": ["feature_selected", "evidence_recorded", "review_requested", "evaluator_passed"],
        "transitions": [
            {"from": "backlog", "event": "feature_selected", "to": "building"},
            {"from": "building", "event": "evidence_recorded", "to": "evidence_ready"},
            {"from": "evidence_ready", "event": "review_requested", "to": "evaluating"},
            {
                "from": "evaluating",
                "event": "evaluator_passed",
                "to": "done",
                "guards": ["evidence_bound_to_criteria"],
            },
        ],
    }


def test_loads_valid_loop_definition():
    definition = LoopDefinition.from_dict(delivery_schema())

    assert definition.id == "software_delivery"
    assert definition.initial_state == "backlog"
    assert definition.transition_for("backlog", "feature_selected").to_state == "building"


def test_rejects_duplicate_states():
    raw = delivery_schema()
    raw["states"].append("backlog")

    with pytest.raises(SchemaError, match="duplicate state"):
        LoopDefinition.from_dict(raw)


def test_rejects_transition_to_unknown_state():
    raw = delivery_schema()
    raw["transitions"].append({"from": "done", "event": "feature_selected", "to": "missing"})

    with pytest.raises(SchemaError, match="unknown state"):
        LoopDefinition.from_dict(raw)


def test_state_machine_applies_allowed_transition():
    machine = StateMachine(LoopDefinition.from_dict(delivery_schema()))

    assert machine.apply("backlog", "feature_selected", satisfied_guards=set()) == "building"


def test_state_machine_rejects_missing_transition():
    machine = StateMachine(LoopDefinition.from_dict(delivery_schema()))

    with pytest.raises(TransitionRejected, match="No transition"):
        machine.apply("backlog", "evaluator_passed", satisfied_guards=set())


def test_state_machine_requires_guards():
    machine = StateMachine(LoopDefinition.from_dict(delivery_schema()))

    with pytest.raises(TransitionRejected, match="Missing guards"):
        machine.apply("evaluating", "evaluator_passed", satisfied_guards=set())

    assert machine.apply(
        "evaluating",
        "evaluator_passed",
        satisfied_guards={"evidence_bound_to_criteria"},
    ) == "done"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/test_state_machine.py -q`

Expected: FAIL because `hook_loop.schema` and `hook_loop.state_machine` do not exist.

- [ ] **Step 3: Implement schema validation**

Create `src/hook_loop/schema.py`:

```python
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

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LoopDefinition":
        loop_id = _required_str(raw, "id")
        initial_state = _required_str(raw, "initial_state")
        states = tuple(_required_str_list(raw, "states"))
        events = tuple(_required_str_list(raw, "events"))
        _reject_duplicates(states, "state")
        _reject_duplicates(events, "event")

        if initial_state not in states:
            raise SchemaError(f"initial_state references unknown state: {initial_state}")

        transitions = tuple(_transition_from_dict(item) for item in raw.get("transitions", []))
        for transition in transitions:
            if transition.from_state not in states:
                raise SchemaError(f"transition references unknown state: {transition.from_state}")
            if transition.to_state not in states:
                raise SchemaError(f"transition references unknown state: {transition.to_state}")
            if transition.event not in events:
                raise SchemaError(f"transition references unknown event: {transition.event}")

        return cls(
            id=loop_id,
            initial_state=initial_state,
            states=states,
            events=events,
            transitions=transitions,
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
        guards=tuple(raw.get("guards", [])),
        actions=tuple(raw.get("actions", [])),
        resume_policy=raw.get("resume_policy"),
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


def _reject_duplicates(values: tuple[str, ...], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise SchemaError(f"duplicate {label}: {value}")
        seen.add(value)
```

- [ ] **Step 4: Implement state transition logic**

Create `src/hook_loop/state_machine.py`:

```python
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
```

- [ ] **Step 5: Run tests and verify they pass**

Run: `uv run pytest tests/test_state_machine.py -q`

Expected: PASS.

- [ ] **Step 6: Run current test suite**

Run: `uv run pytest -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hook_loop/schema.py src/hook_loop/state_machine.py tests/test_state_machine.py
git commit -m "feat: add hook loop state machine contracts"
```

### Task 3: Append-Only Event Log And Recovery

**Files:**
- Create: `src/hook_loop/events.py`
- Create: `src/hook_loop/store.py`
- Create: `tests/test_event_store.py`

- [ ] **Step 1: Write failing event store tests**

Create `tests/test_event_store.py`:

```python
import json

from hook_loop.events import Event, new_event
from hook_loop.store import JsonlEventLog, recover_current_state


def test_appends_and_reads_events(tmp_path):
    path = tmp_path / "hook-loop.jsonl"
    log = JsonlEventLog(path)

    event = new_event(
        session_id="s1",
        run_id="r1",
        state="backlog",
        event_type="session_initialized",
        actor="runtime",
        payload={"initial_state": "backlog"},
    )
    log.append(event)

    assert log.read_all() == [event]
    assert json.loads(path.read_text().splitlines()[0])["event_type"] == "session_initialized"


def test_recovers_current_state_from_state_transition_events(tmp_path):
    path = tmp_path / "hook-loop.jsonl"
    log = JsonlEventLog(path)
    log.append(new_event("s1", "r1", "backlog", "session_initialized", "runtime", {}))
    log.append(new_event("s1", "r1", "building", "state_transitioned", "runtime", {"to": "building"}))
    log.append(new_event("s1", "r1", "building", "hook_fired", "hook", {"stage": "before_turn"}))
    log.append(new_event("s1", "r1", "done", "state_transitioned", "runtime", {"to": "done"}))

    assert recover_current_state(log.read_all()) == "done"


def test_recovers_stopped_state_from_terminal_event(tmp_path):
    path = tmp_path / "hook-loop.jsonl"
    log = JsonlEventLog(path)
    log.append(new_event("s1", "r1", "backlog", "session_initialized", "runtime", {}))
    log.append(new_event("s1", "r1", "stopped", "budget_exhausted", "runtime", {"reason": "max_turns"}))

    assert recover_current_state(log.read_all()) == "stopped"


def test_recovery_returns_none_for_empty_log(tmp_path):
    assert recover_current_state(JsonlEventLog(tmp_path / "empty.jsonl").read_all()) is None
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/test_event_store.py -q`

Expected: FAIL because `events.py` and `store.py` do not exist.

- [ ] **Step 3: Implement events**

Create `src/hook_loop/events.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Event:
    schema_version: int
    event_id: str
    session_id: str
    run_id: str
    timestamp: str
    state: str
    event_type: str
    actor: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Event":
        return cls(
            schema_version=int(raw["schema_version"]),
            event_id=str(raw["event_id"]),
            session_id=str(raw["session_id"]),
            run_id=str(raw["run_id"]),
            timestamp=str(raw["timestamp"]),
            state=str(raw["state"]),
            event_type=str(raw["event_type"]),
            actor=str(raw["actor"]),
            payload=dict(raw.get("payload", {})),
        )


def new_event(
    session_id: str,
    run_id: str,
    state: str,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
) -> Event:
    return Event(
        schema_version=SCHEMA_VERSION,
        event_id=str(uuid4()),
        session_id=session_id,
        run_id=run_id,
        timestamp=datetime.now(UTC).isoformat(),
        state=state,
        event_type=event_type,
        actor=actor,
        payload=payload,
    )
```

- [ ] **Step 4: Implement JSONL store**

Create `src/hook_loop/store.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from hook_loop.events import Event


class JsonlEventLog:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append(self, event: Event) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")

    def read_all(self) -> list[Event]:
        if not self.path.exists():
            return []
        events: list[Event] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    events.append(Event.from_dict(json.loads(line)))
        return events


def recover_current_state(events: list[Event]) -> str | None:
    current: str | None = None
    for event in events:
        if event.event_type == "session_initialized":
            current = event.payload.get("initial_state", event.state)
        elif event.event_type == "state_transitioned":
            current = event.payload.get("to", event.state)
        else:
            current = event.state
    return current
```

- [ ] **Step 5: Run event store tests**

Run: `uv run pytest tests/test_event_store.py -q`

Expected: PASS.

- [ ] **Step 6: Run current test suite**

Run: `uv run pytest -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hook_loop/events.py src/hook_loop/store.py tests/test_event_store.py
git commit -m "feat: add append-only hook loop event log"
```

## Chunk 2: Hooks, Evaluator, And Runtime Simulation

### Task 4: In-Process Hook Bus

**Files:**
- Create: `src/hook_loop/hooks.py`
- Create: `tests/test_hooks.py`

- [ ] **Step 1: Write failing hook bus tests**

Create `tests/test_hooks.py`:

```python
from hook_loop.hooks import HookBus, HookContext, HookDecision


def test_hook_bus_allows_when_no_hooks_registered():
    bus = HookBus()
    decision = bus.fire("before_turn", HookContext(state="backlog", event=None, payload={}))

    assert decision.allowed is True
    assert decision.messages == []


def test_hook_bus_blocks_when_any_hook_blocks():
    bus = HookBus()
    bus.register("before_state_transition", lambda context: HookDecision.block("missing evidence"))

    decision = bus.fire(
        "before_state_transition",
        HookContext(state="evaluating", event="evaluator_passed", payload={}),
    )

    assert decision.allowed is False
    assert decision.messages == ["missing evidence"]


def test_hook_bus_collects_steer_messages():
    bus = HookBus()
    bus.register("before_turn", lambda context: HookDecision.allow("look at NEXT.md"))
    bus.register("before_turn", lambda context: HookDecision.allow("budget: 2 turns left"))

    decision = bus.fire("before_turn", HookContext(state="building", event=None, payload={}))

    assert decision.allowed is True
    assert decision.messages == ["look at NEXT.md", "budget: 2 turns left"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/test_hooks.py -q`

Expected: FAIL because `hook_loop.hooks` does not exist.

- [ ] **Step 3: Implement hook bus**

Create `src/hook_loop/hooks.py`:

```python
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
```

- [ ] **Step 4: Run hook tests and suite**

Run: `uv run pytest tests/test_hooks.py -q`

Expected: PASS.

Run: `uv run pytest -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hook_loop/hooks.py tests/test_hooks.py
git commit -m "feat: add hook bus contract"
```

### Task 5: Evaluator Verdict Parser And Fake Evaluator

**Files:**
- Create: `src/hook_loop/evaluator.py`
- Create: `tests/test_evaluator.py`

- [ ] **Step 1: Write failing evaluator tests**

Create `tests/test_evaluator.py`:

```python
import pytest

from hook_loop.evaluator import FakeEvaluator, Verdict, parse_verdict


def test_parse_pass_verdict():
    verdict = parse_verdict("PASS\nEvidence matched every criterion.")

    assert verdict.status == "PASS"
    assert verdict.details == "Evidence matched every criterion."


def test_parse_needs_work_verdict():
    verdict = parse_verdict("NEEDS_WORK\n- Screenshot missing")

    assert verdict.status == "NEEDS_WORK"
    assert "Screenshot missing" in verdict.details


def test_rejects_unparseable_verdict():
    with pytest.raises(ValueError, match="verdict must start"):
        parse_verdict("looks fine")


def test_fake_evaluator_returns_configured_verdicts_in_order():
    evaluator = FakeEvaluator([
        Verdict(status="NEEDS_WORK", details="- first finding"),
        Verdict(status="PASS", details="all good"),
    ])

    assert evaluator.evaluate({}).status == "NEEDS_WORK"
    assert evaluator.evaluate({}).status == "PASS"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/test_evaluator.py -q`

Expected: FAIL because `hook_loop.evaluator` does not exist.

- [ ] **Step 3: Implement evaluator helpers**

Create `src/hook_loop/evaluator.py`:

```python
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
```

- [ ] **Step 4: Run evaluator tests and suite**

Run: `uv run pytest tests/test_evaluator.py -q`

Expected: PASS.

Run: `uv run pytest -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hook_loop/evaluator.py tests/test_evaluator.py
git commit -m "feat: add evaluator verdict parser"
```

### Task 6: Minimal Runtime Loop Simulation

**Files:**
- Create: `src/hook_loop/runtime.py`
- Create: `tests/test_runtime_simulation.py`

- [ ] **Step 1: Write failing runtime simulation tests**

Create `tests/test_runtime_simulation.py`:

```python
from hook_loop.evaluator import FakeEvaluator, Verdict
from hook_loop.hooks import HookBus, HookContext, HookDecision
from hook_loop.runtime import AgentStep, FakeAgent, LoopRuntime, RuntimeBudget
from hook_loop.schema import LoopDefinition
from hook_loop.store import JsonlEventLog, recover_current_state


def delivery_definition():
    return LoopDefinition.from_dict(
        {
            "id": "software_delivery",
            "initial_state": "backlog",
            "states": ["backlog", "building", "evidence_ready", "evaluating", "needs_work", "done", "stopped"],
            "events": [
                "feature_selected",
                "evidence_recorded",
                "review_requested",
                "evaluator_passed",
                "evaluator_failed",
                "operator_stopped",
            ],
            "transitions": [
                {"from": "backlog", "event": "feature_selected", "to": "building"},
                {"from": "building", "event": "evidence_recorded", "to": "evidence_ready"},
                {"from": "evidence_ready", "event": "review_requested", "to": "evaluating"},
                {
                    "from": "evaluating",
                    "event": "evaluator_passed",
                    "to": "done",
                    "guards": ["evidence_bound_to_criteria"],
                },
                {"from": "evaluating", "event": "evaluator_failed", "to": "needs_work"},
                {"from": "needs_work", "event": "feature_selected", "to": "building"},
            ],
        }
    )


def test_runtime_reaches_done_on_pass(tmp_path):
    runtime = LoopRuntime(
        definition=delivery_definition(),
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        agent=FakeAgent(
            {
                "backlog": [AgentStep("feature_selected")],
                "building": [AgentStep("evidence_recorded", {"evidence_id": "e1"})],
                "evidence_ready": [AgentStep("review_requested")],
            }
        ),
        evaluator=FakeEvaluator([Verdict("PASS", "evidence checked")]),
    )

    final_state = runtime.run_until_stop(RuntimeBudget(max_turns=5))

    assert final_state == "done"
    assert recover_current_state(runtime.store.read_all()) == "done"


def test_runtime_reworks_after_needs_work(tmp_path):
    runtime = LoopRuntime(
        definition=delivery_definition(),
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        agent=FakeAgent(
            {
                "backlog": [AgentStep("feature_selected")],
                "needs_work": [AgentStep("feature_selected")],
                "building": [
                    AgentStep("evidence_recorded", {"evidence_id": "first"}),
                    AgentStep("evidence_recorded", {"evidence_id": "second"}),
                ],
                "evidence_ready": [AgentStep("review_requested"), AgentStep("review_requested")],
            }
        ),
        evaluator=FakeEvaluator([
            Verdict("NEEDS_WORK", "- missing screenshot"),
            Verdict("PASS", "fixed"),
        ]),
    )

    final_state = runtime.run_until_stop(RuntimeBudget(max_turns=8))

    assert final_state == "done"
    event_types = [event.event_type for event in runtime.store.read_all()]
    assert event_types.count("verdict_recorded") == 2


def test_runtime_stops_on_no_progress_budget(tmp_path):
    runtime = LoopRuntime(
        definition=delivery_definition(),
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        agent=FakeAgent({"backlog": []}),
        evaluator=FakeEvaluator([]),
    )

    final_state = runtime.run_until_stop(RuntimeBudget(max_turns=2, max_no_progress_turns=1))

    assert final_state == "stopped"
    assert runtime.store.read_all()[-1].event_type == "budget_exhausted"


def test_runtime_blocks_transition_when_hook_blocks(tmp_path):
    hooks = HookBus()

    def require_evidence(context: HookContext) -> HookDecision:
        if context.event == "evaluator_passed":
            return HookDecision.block("missing bound evidence")
        return HookDecision.allow()

    hooks.register("before_state_transition", require_evidence)
    runtime = LoopRuntime(
        definition=delivery_definition(),
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        agent=FakeAgent(
            {
                "backlog": [AgentStep("feature_selected")],
                "building": [AgentStep("evidence_recorded", {"evidence_id": "e3"})],
                "evidence_ready": [AgentStep("review_requested")],
            }
        ),
        evaluator=FakeEvaluator([Verdict("PASS", "claimed pass")]),
        hooks=hooks,
    )

    final_state = runtime.run_until_stop(RuntimeBudget(max_turns=5))

    assert final_state == "stopped"
    assert runtime.store.read_all()[-1].event_type == "transition_blocked"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/test_runtime_simulation.py -q`

Expected: FAIL because `hook_loop.runtime` does not exist.

- [ ] **Step 3: Implement runtime types and fake agent**

Create `src/hook_loop/runtime.py` with these imports and simple helper classes:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from hook_loop.evaluator import FakeEvaluator, Verdict
from hook_loop.events import new_event
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
```

- [ ] **Step 4: Implement `LoopRuntime`**

Continue `src/hook_loop/runtime.py`:

```python
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
        self.current_state = recover_current_state(store.read_all()) or definition.initial_state

    def run_until_stop(self, budget: RuntimeBudget) -> str:
        if not self.store.read_all():
            self._append("session_initialized", "runtime", {"initial_state": self.current_state})

        no_progress_turns = 0
        for _ in range(budget.max_turns):
            if self.current_state in {"done", "stopped"}:
                return self.current_state

            before = self.hooks.fire("before_turn", HookContext(self.current_state, None, {}))
            if not before.allowed:
                return self._stop("transition_blocked", {"messages": before.messages})

            progressed = False
            for step in self.agent.next_steps(self.current_state):
                progressed = self._apply_step(step) or progressed
                if self.current_state == "evaluating":
                    progressed = self._evaluate() or progressed

            if progressed:
                no_progress_turns = 0
            else:
                no_progress_turns += 1
                if no_progress_turns >= budget.max_no_progress_turns:
                    return self._stop("budget_exhausted", {"reason": "no productive event"})

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
```

- [ ] **Step 5: Run runtime simulation tests**

Run: `uv run pytest tests/test_runtime_simulation.py -q`

Expected: PASS.

- [ ] **Step 6: Run full suite**

Run: `uv run pytest -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hook_loop/runtime.py tests/test_runtime_simulation.py
git commit -m "feat: add minimal hook loop runtime simulation"
```

### Task 7: Public Exports And Final Verification

**Files:**
- Modify: `src/hook_loop/__init__.py`
- Modify: `tests/test_package_import.py`

- [ ] **Step 1: Expand package import test**

Update `tests/test_package_import.py`:

```python
def test_package_imports():
    import hook_loop

    assert hook_loop.__version__ == "0.1.0"
    assert hook_loop.LoopDefinition is not None
    assert hook_loop.StateMachine is not None
    assert hook_loop.JsonlEventLog is not None
    assert hook_loop.LoopRuntime is not None
```

- [ ] **Step 2: Run test and verify it fails**

Run: `uv run pytest tests/test_package_import.py -q`

Expected: FAIL because the public exports are missing.

- [ ] **Step 3: Export public runtime API**

Update `src/hook_loop/__init__.py`:

```python
"""Platform-neutral hook loop runtime."""

from hook_loop.events import Event, new_event
from hook_loop.evaluator import FakeEvaluator, Verdict, parse_verdict
from hook_loop.hooks import HookBus, HookContext, HookDecision
from hook_loop.runtime import AgentStep, FakeAgent, LoopRuntime, RuntimeBudget
from hook_loop.schema import LoopDefinition, SchemaError, Transition
from hook_loop.state_machine import StateMachine, TransitionRejected
from hook_loop.store import JsonlEventLog, recover_current_state

__version__ = "0.1.0"

__all__ = [
    "AgentStep",
    "Event",
    "FakeAgent",
    "FakeEvaluator",
    "HookBus",
    "HookContext",
    "HookDecision",
    "JsonlEventLog",
    "LoopDefinition",
    "LoopRuntime",
    "RuntimeBudget",
    "SchemaError",
    "StateMachine",
    "Transition",
    "TransitionRejected",
    "Verdict",
    "new_event",
    "parse_verdict",
    "recover_current_state",
]
```

- [ ] **Step 4: Run full verification**

Run: `uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Inspect working tree**

Run: `git status --short`

Expected: only the intended B-stage runtime files are modified or untracked. Do not stage `.gitignore` or `docs/research/**`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/hook_loop tests
git commit -m "feat: expose minimal hook loop runtime"
```

## Implementation Notes

- The runtime is intentionally in-process and fake-agent based. That keeps B-stage deterministic and testable without a real LLM.
- The hook bus is not a security boundary. It models allow/block/steer semantics for later adapter work.
- The schema loader accepts Python dictionaries for B-stage. A YAML/JSON DSL parser belongs to C-stage.
- The runtime can be made more sophisticated after the simulation tests prove the core loop semantics.

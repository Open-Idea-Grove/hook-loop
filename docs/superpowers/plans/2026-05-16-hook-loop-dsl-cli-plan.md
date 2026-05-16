# Hook Loop DSL And CLI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the C-stage minimal user-facing path: load a JSON loop DSL, validate it, run deterministic simulations, and expose those flows through a small `hook-loop` CLI.

**Architecture:** Keep the platform-neutral B-stage runtime as the execution core. Add a thin JSON DSL layer that converts user-authored files into `LoopDefinition`, `RuntimeBudget`, `FakeAgent`, and `FakeEvaluator` objects. Add a CLI that calls the same public APIs used by tests; do not add Codex, Claude Code, pi, or hook-script adapters in this plan.

**Tech Stack:** Python 3.11+, standard library `json` and `argparse`, pytest via `uv run pytest`, package scripts managed by uv.

---

## Constraints

- Implement C-stage loader and CLI only. Do not implement platform adapters or generated hook scripts.
- Use JSON only for the first DSL format. Do not add YAML or third-party dependencies.
- Keep runtime semantics state-machine-first. User-authored terminal and stop states must come from schema, not hardcoded platform assumptions.
- Do not stage or modify unrelated worktree changes such as `.gitignore` or `docs/research/**`.
- Prefer TDD: failing test, expected failure, minimal implementation, passing verification, then commit.
- Every Python command in this plan uses uv.

## Constitution Check

- **State-machine-first**: PASS. The plan adds explicit `terminal_states` and `stop_state` to the schema before exposing user-defined DSL files.
- **Platform-neutral core**: PASS. The CLI uses the same runtime primitives and does not add platform-specific adapters.
- **Evidence and recovery**: PASS. Simulation writes the existing append-only JSONL event log and validates recovered final state.
- **Test-first runtime semantics**: PASS. Each task begins with failing tests and ends with focused and full test runs.
- **Python uses uv**: PASS. All commands use `uv run` or `uv sync`.

## File Structure

- Modify `src/hook_loop/schema.py`: add `terminal_states` and `stop_state` to `LoopDefinition` with validation.
- Modify `src/hook_loop/runtime.py`: use `definition.terminal_states` for terminal detection and `definition.stop_state` for runtime stops.
- Create `src/hook_loop/dsl.py`: JSON DSL loader, `LoopSpec`, and deterministic simulation config parsing.
- Create `src/hook_loop/cli.py`: `hook-loop validate` and `hook-loop simulate` commands.
- Modify `src/hook_loop/__init__.py`: export DSL loader types and functions.
- Modify `pyproject.toml`: add `[project.scripts] hook-loop = "hook_loop.cli:main"`.
- Create `examples/software_delivery.json`: canonical minimal DSL example.
- Create `tests/test_dsl.py`: DSL loader and example tests.
- Create `tests/test_cli.py`: CLI validate/simulate tests.
- Modify `tests/test_runtime_simulation.py`: terminal-state behavior test.
- Modify `tests/test_package_import.py`: public DSL exports smoke test.
- Modify `README.md`: document JSON DSL and CLI verification.

## Chunk 1: User-Defined State Semantics

### Task 1: Add Schema-Defined Terminal And Stop States

**Files:**
- Modify: `src/hook_loop/schema.py`
- Modify: `src/hook_loop/runtime.py`
- Modify: `tests/test_state_machine.py`
- Modify: `tests/test_runtime_simulation.py`

- [ ] **Step 1: Write failing schema tests**

Add these tests to `tests/test_state_machine.py`:

```python
def test_loads_terminal_and_stop_states_from_schema():
    raw = delivery_schema()
    raw["states"].append("stopped")
    raw["terminal_states"] = ["done", "stopped"]
    raw["stop_state"] = "stopped"

    definition = LoopDefinition.from_dict(raw)

    assert definition.terminal_states == ("done", "stopped")
    assert definition.stop_state == "stopped"


def test_rejects_terminal_state_not_in_states():
    raw = delivery_schema()
    raw["terminal_states"] = ["missing"]

    with pytest.raises(SchemaError, match="terminal state"):
        LoopDefinition.from_dict(raw)


def test_rejects_stop_state_not_in_terminal_states():
    raw = delivery_schema()
    raw["states"].append("stopped")
    raw["terminal_states"] = ["done"]
    raw["stop_state"] = "stopped"

    with pytest.raises(SchemaError, match="stop_state"):
        LoopDefinition.from_dict(raw)
```

- [ ] **Step 2: Write failing runtime test for custom terminal states**

Add this test to `tests/test_runtime_simulation.py`:

```python
def accepted_terminal_definition():
    return LoopDefinition.from_dict(
        {
            "id": "approval_loop",
            "initial_state": "draft",
            "states": ["draft", "evaluating", "accepted", "stopped"],
            "terminal_states": ["accepted", "stopped"],
            "stop_state": "stopped",
            "events": ["submit", "evaluator_passed"],
            "transitions": [
                {"from": "draft", "event": "submit", "to": "evaluating"},
                {
                    "from": "evaluating",
                    "event": "evaluator_passed",
                    "to": "accepted",
                    "guards": ["evidence_bound_to_criteria"],
                },
            ],
        }
    )


def test_runtime_uses_schema_terminal_states(tmp_path):
    runtime = LoopRuntime(
        definition=accepted_terminal_definition(),
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        agent=FakeAgent({"draft": [AgentStep("submit")]}),
        evaluator=FakeEvaluator([Verdict("PASS", "accepted")]),
    )

    assert runtime.run_until_stop(RuntimeBudget(max_turns=2)) == "accepted"
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
uv run pytest tests/test_state_machine.py tests/test_runtime_simulation.py -q
```

Expected: FAIL because `LoopDefinition` has no `terminal_states` or `stop_state`, and runtime terminal/stop handling is hardcoded.

- [ ] **Step 4: Implement terminal state validation**

Update `LoopDefinition` in `src/hook_loop/schema.py`:

```python
@dataclass(frozen=True)
class LoopDefinition:
    id: str
    initial_state: str
    states: tuple[str, ...]
    events: tuple[str, ...]
    transitions: tuple[Transition, ...]
    terminal_states: tuple[str, ...]
    stop_state: str | None = None
```

Inside `LoopDefinition.from_dict`, after `states` and `events` are loaded:

```python
default_terminal_states = [state for state in ("done", "stopped") if state in states]
terminal_states = tuple(raw.get("terminal_states", default_terminal_states))
if not terminal_states or not all(isinstance(item, str) and item for item in terminal_states):
    raise SchemaError("terminal_states must be a non-empty list of strings")
_reject_duplicates(terminal_states, "terminal state")
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
```

Add `terminal_states=terminal_states` and `stop_state=stop_state` to the returned `LoopDefinition`.

- [ ] **Step 5: Update runtime terminal detection**

Change terminal detection and stop handling in `src/hook_loop/runtime.py`:

```python
def _is_terminal(self) -> bool:
    return self.current_state in self.definition.terminal_states


def _stop(self, event_type: str, payload: dict[str, Any]) -> str:
    if self.definition.stop_state is None:
        raise RuntimeError("LoopDefinition requires stop_state for runtime stop")
    self.current_state = self.definition.stop_state
    self._append(event_type, "runtime", payload)
    return self.current_state
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/test_state_machine.py tests/test_runtime_simulation.py -q
```

Expected: PASS.

- [ ] **Step 7: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/hook_loop/schema.py src/hook_loop/runtime.py tests/test_state_machine.py tests/test_runtime_simulation.py
git commit -m "feat: support schema-defined terminal states"
```

## Chunk 2: JSON DSL Loader

### Task 2: Load LoopSpec From JSON

**Files:**
- Create: `src/hook_loop/dsl.py`
- Create: `tests/test_dsl.py`

- [ ] **Step 1: Write failing DSL loader tests**

Create `tests/test_dsl.py`:

```python
import json

import pytest

from hook_loop.dsl import DslError, LoopSpec, load_loop_spec


def valid_dsl():
    return {
        "loop": {
            "id": "software_delivery",
            "initial_state": "backlog",
            "states": ["backlog", "building", "evidence_ready", "evaluating", "done", "stopped"],
            "terminal_states": ["done", "stopped"],
            "stop_state": "stopped",
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
        },
        "simulation": {
            "budget": {"max_turns": 3, "max_no_progress_turns": 1},
            "agent_steps": {
                "backlog": [{"event": "feature_selected"}],
                "building": [{"event": "evidence_recorded", "payload": {"evidence_id": "e1"}}],
                "evidence_ready": [{"event": "review_requested"}],
            },
            "verdicts": [{"status": "PASS", "details": "evidence checked"}],
        },
    }


def test_loads_loop_spec_from_json(tmp_path):
    path = tmp_path / "loop.json"
    path.write_text(json.dumps(valid_dsl()), encoding="utf-8")

    spec = load_loop_spec(path)

    assert isinstance(spec, LoopSpec)
    assert spec.definition.id == "software_delivery"
    assert spec.simulation.budget.max_turns == 3
    assert spec.simulation.agent_steps["building"][0].payload == {"evidence_id": "e1"}
    assert spec.simulation.verdicts[0].status == "PASS"


def test_rejects_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(DslError, match="invalid JSON"):
        load_loop_spec(path)


def test_rejects_missing_loop_object(tmp_path):
    path = tmp_path / "missing-loop.json"
    path.write_text(json.dumps({"simulation": {}}), encoding="utf-8")

    with pytest.raises(DslError, match="loop"):
        load_loop_spec(path)


def test_rejects_missing_stop_state(tmp_path):
    path = tmp_path / "missing-stop.json"
    raw = valid_dsl()
    del raw["loop"]["stop_state"]
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DslError, match="stop_state"):
        load_loop_spec(path)


def test_rejects_missing_file():
    with pytest.raises(DslError, match="cannot read"):
        load_loop_spec("missing.json")


def test_rejects_simulation_step_for_unknown_state(tmp_path):
    path = tmp_path / "loop.json"
    raw = valid_dsl()
    raw["simulation"]["agent_steps"]["missing"] = [{"event": "feature_selected"}]
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DslError, match="unknown state"):
        load_loop_spec(path)


def test_rejects_simulation_step_for_missing_transition(tmp_path):
    path = tmp_path / "loop.json"
    raw = valid_dsl()
    raw["simulation"]["agent_steps"]["backlog"] = [{"event": "review_requested"}]
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DslError, match="No transition"):
        load_loop_spec(path)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run pytest tests/test_dsl.py -q
```

Expected: FAIL because `hook_loop.dsl` does not exist.

- [ ] **Step 3: Implement DSL dataclasses and loader**

Create `src/hook_loop/dsl.py`:

```python
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
    try:
        definition = LoopDefinition.from_dict(loop_raw)
    except SchemaError as exc:
        raise DslError(str(exc)) from exc
    simulation = _parse_simulation(raw.get("simulation", {}))
    _validate_loop_spec(definition, simulation)
    return LoopSpec(
        definition=definition,
        simulation=simulation,
    )


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
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_dsl.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hook_loop/dsl.py tests/test_dsl.py
git commit -m "feat: load hook loop JSON DSL"
```

### Task 3: Add Canonical Example DSL

**Files:**
- Create: `examples/software_delivery.json`
- Modify: `tests/test_dsl.py`

- [ ] **Step 1: Create example regression test**

Add this test to `tests/test_dsl.py`:

```python
from pathlib import Path

from hook_loop.evaluator import FakeEvaluator
from hook_loop.runtime import FakeAgent, LoopRuntime
from hook_loop.store import JsonlEventLog, recover_current_state


def test_software_delivery_example_simulates_to_done(tmp_path):
    spec = load_loop_spec(Path("examples/software_delivery.json"))
    runtime = LoopRuntime(
        definition=spec.definition,
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        agent=FakeAgent({state: list(steps) for state, steps in spec.simulation.agent_steps.items()}),
        evaluator=FakeEvaluator(list(spec.simulation.verdicts)),
    )

    final_state = runtime.run_until_stop(spec.simulation.budget)

    assert final_state == "done"
    assert recover_current_state(runtime.store.read_all()) == "done"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
uv run pytest tests/test_dsl.py::test_software_delivery_example_simulates_to_done -q
```

Expected: FAIL because `examples/software_delivery.json` does not exist.

- [ ] **Step 3: Create canonical example**

Create `examples/software_delivery.json`:

```json
{
  "loop": {
    "id": "software_delivery",
    "initial_state": "backlog",
    "states": ["backlog", "building", "evidence_ready", "evaluating", "done", "stopped"],
    "terminal_states": ["done", "stopped"],
    "stop_state": "stopped",
    "events": ["feature_selected", "evidence_recorded", "review_requested", "evaluator_passed"],
    "transitions": [
      {"from": "backlog", "event": "feature_selected", "to": "building"},
      {"from": "building", "event": "evidence_recorded", "to": "evidence_ready"},
      {"from": "evidence_ready", "event": "review_requested", "to": "evaluating"},
      {
        "from": "evaluating",
        "event": "evaluator_passed",
        "to": "done",
        "guards": ["evidence_bound_to_criteria"]
      }
    ]
  },
  "simulation": {
    "budget": {"max_turns": 3, "max_no_progress_turns": 1},
    "agent_steps": {
      "backlog": [{"event": "feature_selected"}],
      "building": [{"event": "evidence_recorded", "payload": {"evidence_id": "e1"}}],
      "evidence_ready": [{"event": "review_requested"}]
    },
    "verdicts": [{"status": "PASS", "details": "evidence checked"}]
  }
}
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_dsl.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add examples/software_delivery.json tests/test_dsl.py
git commit -m "test: add canonical hook loop DSL example"
```

## Chunk 3: CLI Validate And Simulate

### Task 4: Add `hook-loop validate`

**Files:**
- Create: `src/hook_loop/cli.py`
- Modify: `pyproject.toml`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI validate tests**

Create `tests/test_cli.py`:

```python
import json

from hook_loop.cli import main
from tests.test_dsl import valid_dsl


def test_validate_command_accepts_valid_dsl(tmp_path, capsys):
    path = tmp_path / "loop.json"
    path.write_text(json.dumps(valid_dsl()), encoding="utf-8")

    exit_code = main(["validate", str(path)])

    assert exit_code == 0
    assert "valid: software_delivery" in capsys.readouterr().out


def test_validate_command_rejects_invalid_dsl(tmp_path, capsys):
    path = tmp_path / "loop.json"
    raw = valid_dsl()
    raw["loop"]["terminal_states"] = ["missing"]
    path.write_text(json.dumps(raw), encoding="utf-8")

    exit_code = main(["validate", str(path)])

    assert exit_code == 1
    assert "invalid:" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run pytest tests/test_cli.py -q
```

Expected: FAIL because `hook_loop.cli` does not exist.

- [ ] **Step 3: Implement validate CLI**

Create `src/hook_loop/cli.py`:

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hook_loop.dsl import DslError, load_loop_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hook-loop")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate a hook loop JSON DSL file")
    validate.add_argument("path", type=Path)

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.path)
    parser.error(f"unknown command: {args.command}")
    return 2


def _validate(path: Path) -> int:
    try:
        spec = load_loop_spec(path)
    except DslError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    print(f"valid: {spec.definition.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Modify `pyproject.toml`:

```toml
[project.scripts]
hook-loop = "hook_loop.cli:main"
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 5: Verify project script manually**

Run:

```bash
uv run hook-loop validate examples/software_delivery.json
```

Expected output includes:

```text
valid: software_delivery
```

- [ ] **Step 6: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/hook_loop/cli.py tests/test_cli.py
git commit -m "feat: add hook loop validate CLI"
```

### Task 5: Add `hook-loop simulate`

**Files:**
- Modify: `src/hook_loop/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing simulate CLI test**

Add this test to `tests/test_cli.py`:

```python
def test_simulate_command_runs_dsl_simulation(tmp_path, capsys):
    path = tmp_path / "loop.json"
    event_log = tmp_path / "events.jsonl"
    path.write_text(json.dumps(valid_dsl()), encoding="utf-8")

    exit_code = main(["simulate", str(path), "--event-log", str(event_log)])

    assert exit_code == 0
    assert "final_state: done" in capsys.readouterr().out
    assert event_log.exists()
    assert "state_transitioned" in event_log.read_text(encoding="utf-8")


def test_simulate_command_reports_runtime_errors(tmp_path, capsys):
    path = tmp_path / "loop.json"
    raw = valid_dsl()
    raw["simulation"]["verdicts"] = []
    path.write_text(json.dumps(raw), encoding="utf-8")

    exit_code = main(["simulate", str(path), "--event-log", str(tmp_path / "events.jsonl")])

    assert exit_code == 1
    assert "simulation failed:" in capsys.readouterr().err
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
uv run pytest tests/test_cli.py::test_simulate_command_runs_dsl_simulation -q
```

Expected: FAIL because `simulate` command is not registered.

- [ ] **Step 3: Implement simulate command**

Update `src/hook_loop/cli.py`:

```python
from hook_loop.evaluator import FakeEvaluator
from hook_loop.runtime import FakeAgent, LoopRuntime
from hook_loop.store import JsonlEventLog
```

Register the subcommand in `main`:

```python
simulate = subparsers.add_parser("simulate", help="run a deterministic hook loop simulation")
simulate.add_argument("path", type=Path)
simulate.add_argument("--event-log", type=Path, default=Path("hook-loop-events.jsonl"))
simulate.add_argument("--session-id", default="session-1")
```

Dispatch it:

```python
if args.command == "simulate":
    return _simulate(args.path, args.event_log, args.session_id)
```

Add:

```python
def _simulate(path: Path, event_log: Path, session_id: str) -> int:
    try:
        spec = load_loop_spec(path)
    except DslError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    try:
        runtime = LoopRuntime(
            definition=spec.definition,
            store=JsonlEventLog(event_log),
            agent=FakeAgent({state: list(steps) for state, steps in spec.simulation.agent_steps.items()}),
            evaluator=FakeEvaluator(list(spec.simulation.verdicts)),
            session_id=session_id,
        )
        final_state = runtime.run_until_stop(spec.simulation.budget)
    except RuntimeError as exc:
        print(f"simulation failed: {exc}", file=sys.stderr)
        return 1
    print(f"final_state: {final_state}")
    print(f"event_log: {event_log}")
    return 0 if final_state in spec.definition.terminal_states else 1
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 5: Verify project script manually**

Run:

```bash
uv run hook-loop simulate examples/software_delivery.json --event-log /private/tmp/hook-loop-example.jsonl
```

Expected output includes:

```text
final_state: done
```

- [ ] **Step 6: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hook_loop/cli.py tests/test_cli.py
git commit -m "feat: add hook loop simulate CLI"
```

## Chunk 4: Public API And Documentation

### Task 6: Export DSL API

**Files:**
- Modify: `src/hook_loop/__init__.py`
- Modify: `tests/test_package_import.py`

- [ ] **Step 1: Write failing public export assertions**

Update `tests/test_package_import.py`:

```python
def test_package_imports():
    import hook_loop

    assert hook_loop.__version__ == "0.1.0"
    assert hook_loop.LoopDefinition is not None
    assert hook_loop.StateMachine is not None
    assert hook_loop.JsonlEventLog is not None
    assert hook_loop.LoopRuntime is not None
    assert hook_loop.LoopSpec is not None
    assert hook_loop.load_loop_spec is not None
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
uv run pytest tests/test_package_import.py -q
```

Expected: FAIL because DSL exports are missing.

- [ ] **Step 3: Export DSL API**

Update `src/hook_loop/__init__.py`:

```python
from hook_loop.dsl import DslError, LoopSpec, SimulationSpec, load_loop_spec
```

Add these names to `__all__`:

```python
"DslError",
"LoopSpec",
"SimulationSpec",
"load_loop_spec",
```

- [ ] **Step 4: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hook_loop/__init__.py tests/test_package_import.py
git commit -m "feat: export hook loop DSL API"
```

### Task 7: Document DSL And CLI Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

Add sections for:

- `examples/software_delivery.json`
- `uv run hook-loop validate examples/software_delivery.json`
- `uv run hook-loop simulate examples/software_delivery.json --event-log /private/tmp/hook-loop-example.jsonl`
- The expected outputs: `valid: software_delivery` and `final_state: done`
- The updated full-suite expected test count.

- [ ] **Step 2: Run README commands**

Run:

```bash
uv run hook-loop validate examples/software_delivery.json
```

Expected:

```text
valid: software_delivery
```

Run:

```bash
uv run hook-loop simulate examples/software_delivery.json --event-log /private/tmp/hook-loop-example.jsonl
```

Expected output includes:

```text
final_state: done
```

- [ ] **Step 3: Run full verification**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 4: Inspect working tree**

Run:

```bash
git status --short
```

Expected: only intended files are modified or untracked. Do not stage `.gitignore` or `docs/research/**`.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document hook loop DSL CLI"
```

## Final Verification

After all tasks complete:

```bash
uv sync
uv run pytest -q
uv run hook-loop validate examples/software_delivery.json
uv run hook-loop simulate examples/software_delivery.json --event-log /private/tmp/hook-loop-example.jsonl
git status --short
```

Expected:

- Test suite passes.
- Validate command prints `valid: software_delivery`.
- Simulate command prints `final_state: done`.
- Remaining unstaged/untracked work, if any, is unrelated pre-existing work such as `.gitignore` or `docs/research/**`.

## Implementation Notes

- The DSL file is not a platform adapter. It is a portable loop contract plus deterministic simulation config.
- `simulation` is optional for validation, but required for useful `simulate` runs.
- The CLI should return non-zero for invalid DSL files.
- The simulation command should not delete or overwrite unrelated files except the event log path explicitly provided by the operator.
- Custom terminal state support is deliberately first because user-defined states are not truly user-defined if runtime termination is hardcoded.

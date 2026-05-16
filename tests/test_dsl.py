import json
from pathlib import Path

import pytest

from hook_loop.evaluator import FakeEvaluator
from hook_loop.runtime import FakeAgent, LoopRuntime
from hook_loop.store import JsonlEventLog, recover_current_state
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

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


def test_rejects_duplicate_transitions():
    raw = delivery_schema()
    raw["transitions"].append({"from": "backlog", "event": "feature_selected", "to": "done"})

    with pytest.raises(SchemaError, match="duplicate transition"):
        LoopDefinition.from_dict(raw)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("guards", "evidence_bound_to_criteria"),
        ("actions", "record_evidence"),
        ("resume_policy", ["resume"]),
    ],
)
def test_rejects_transition_metadata_with_wrong_type(key, value):
    raw = delivery_schema()
    raw["transitions"][0][key] = value

    with pytest.raises(SchemaError, match=key):
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

    assert (
        machine.apply(
            "evaluating",
            "evaluator_passed",
            satisfied_guards={"evidence_bound_to_criteria"},
        )
        == "done"
    )

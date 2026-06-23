from hook_loop.driver import ApplyResult, DefaultGuardEvaluator, EventSourcedLoopDriver
from hook_loop.schema import LoopDefinition
from hook_loop.store import JsonlEventLog, recover_current_state


def delivery_definition():
    return LoopDefinition.from_dict(
        {
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
        }
    )


def test_current_state_starts_at_initial_state(tmp_path):
    driver = EventSourcedLoopDriver(
        delivery_definition(),
        JsonlEventLog(tmp_path / "events.jsonl"),
        session_id="s1",
    )

    assert driver.current_state == "backlog"
    assert driver.is_terminal() is False


def test_apply_event_transitions_and_records_state_transitioned(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    driver = EventSourcedLoopDriver(delivery_definition(), log, session_id="s1")

    result = driver.apply_event("feature_selected", {})

    assert result.applied is True
    assert result.rejected is False
    assert result.from_state == "backlog"
    assert result.to_state == "building"
    assert driver.current_state == "building"
    events = log.read_all()
    assert events[-1].event_type == "state_transitioned"
    assert events[-1].payload["from"] == "backlog"
    assert events[-1].payload["to"] == "building"
    assert events[-1].state == "building"


def test_apply_event_missing_guard_is_rejected_without_state_change(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    driver = EventSourcedLoopDriver(delivery_definition(), log, session_id="s1")
    driver.apply_event("feature_selected", {})
    driver.apply_event("evidence_recorded", {})
    driver.apply_event("review_requested", {})
    assert driver.current_state == "evaluating"

    result = driver.apply_event("evaluator_passed", {})

    assert result.applied is False
    assert result.rejected is True
    assert result.from_state == "evaluating"
    assert result.to_state == "evaluating"
    assert "evidence_bound_to_criteria" in (result.reason or "")
    assert driver.current_state == "evaluating"
    assert log.read_all()[-1].event_type == "transition_rejected"


def test_guard_satisfied_by_recorded_evidence_allows_transition(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    driver = EventSourcedLoopDriver(delivery_definition(), log, session_id="s1")
    driver.apply_event("feature_selected", {})
    driver.apply_event("evidence_recorded", {})
    driver.apply_event("review_requested", {})

    # The default guard evaluator treats evidence_registered events as satisfying
    # evidence_bound_to_criteria. Record one directly in the session log.
    from hook_loop.events import new_event

    log.append(
        new_event("s1", "r1", "evaluating", "evidence_registered", "codex", {"kind": "verification"})
    )

    result = driver.apply_event("evaluator_passed", {})

    assert result.applied is True
    assert result.to_state == "done"
    assert driver.current_state == "done"
    assert driver.is_terminal() is True


def test_explicit_guards_satisfy_transition_guards(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    driver = EventSourcedLoopDriver(delivery_definition(), log, session_id="s1")
    driver.apply_event("feature_selected", {})
    driver.apply_event("evidence_recorded", {})
    driver.apply_event("review_requested", {})

    result = driver.apply_event("evaluator_passed", {}, explicit_guards={"evidence_bound_to_criteria"})

    assert result.applied is True
    assert result.to_state == "done"


def test_apply_event_with_no_matching_transition_is_rejected(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    driver = EventSourcedLoopDriver(delivery_definition(), log, session_id="s1")

    result = driver.apply_event("review_requested", {})

    assert result.applied is False
    assert result.rejected is True
    assert "No transition" in (result.reason or "")
    assert driver.current_state == "backlog"
    assert log.read_all()[-1].event_type == "transition_rejected"


def test_recover_current_state_across_driver_instances(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    driver = EventSourcedLoopDriver(delivery_definition(), log, session_id="s1")
    driver.apply_event("feature_selected", {})
    driver.apply_event("evidence_recorded", {})

    rebuilt = EventSourcedLoopDriver(delivery_definition(), log, session_id="s1")

    assert rebuilt.current_state == "evidence_ready"
    assert recover_current_state(log.read_all()) == "evidence_ready"


def test_default_guard_evaluator_unknown_guard_is_not_satisfied(tmp_path):
    evaluator = DefaultGuardEvaluator()

    assert evaluator.is_satisfied("evidence_bound_to_criteria", []) is False
    assert evaluator.is_satisfied("unknown_guard", []) is False

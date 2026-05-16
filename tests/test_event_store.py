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

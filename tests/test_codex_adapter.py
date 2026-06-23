import json
from pathlib import Path

from hook_loop.codex_adapter import handle_codex_hook, normalize_codex_hook_input
from hook_loop.dsl import load_loop_spec
from hook_loop.store import JsonlEventLog


def software_delivery_dsl():
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
        "codex": {
            "event_map": [
                {
                    "codex_event": "UserPromptSubmit",
                    "when": {"prompt_not_match": "(?i)verdict"},
                    "emit": "feature_selected",
                    "comment": "first non-verdict prompt kicks off backlog->building",
                },
                {
                    "codex_event": "PostToolUse",
                    "when": {
                        "tool_name": "Bash",
                        "command_match": "pytest|test|git diff --check|lint|mypy",
                        "exit_code": 0,
                    },
                    "record": {
                        "event_type": "evidence_registered",
                        "actor": "codex",
                        "payload": {"kind": "verification"},
                        "include": ["command", "exit_code", "stdout"],
                    },
                    "emit": "evidence_recorded",
                    "comment": "building->evidence_ready",
                },
                {
                    "codex_event": "UserPromptSubmit",
                    "when": {"prompt_match": "(?i)verdict.*PASS|PASS.*verdict"},
                    "record": {
                        "event_type": "verdict_recorded",
                        "actor": "evaluator",
                        "payload": {"status": "PASS"},
                        "include": ["prompt"],
                    },
                    "emit": "review_requested",
                    "comment": "evidence_ready->evaluating",
                },
                {
                    "codex_event": "UserPromptSubmit",
                    "when": {"prompt_match": "(?i)verdict.*PASS|PASS.*verdict"},
                    "emit": "evaluator_passed",
                    "guard_satisfied": ["evidence_bound_to_criteria"],
                    "comment": "evaluating->done (guard satisfied by recorded evidence)",
                },
            ]
        },
    }


def load_spec(tmp_path) -> "object":
    path = tmp_path / "loop.json"
    path.write_text(json.dumps(software_delivery_dsl()), encoding="utf-8")
    return load_loop_spec(path)


def test_normalizes_codex_pre_tool_use_payload():
    context = normalize_codex_hook_input(
        "PreToolUse",
        {
            "session_id": "session-1",
            "run_id": "run-1",
            "cwd": "/repo",
            "tool_name": "Bash",
            "tool_input": {"command": "uv run pytest -q"},
        },
    )

    assert context.platform == "codex"
    assert context.hook_event_name == "PreToolUse"
    assert context.session_id == "session-1"
    assert context.run_id == "run-1"
    assert context.cwd == "/repo"
    assert context.tool_name == "Bash"
    assert context.tool_input == {"command": "uv run pytest -q"}
    assert context.event == "action_requested"


def test_pre_tool_use_blocks_risky_bash_and_records_event(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    spec = load_spec(tmp_path)

    result = handle_codex_hook(
        event_name="PreToolUse",
        raw_input={
            "session_id": "session-1",
            "run_id": "run-1",
            "cwd": "/repo",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf .git"},
        },
        store=log,
        spec=spec,
    )

    assert result.exit_code == 2
    assert "risky action" in result.stdout
    events = log.read_all()
    assert events[-1].event_type == "hook_fired"
    assert events[-1].payload["verdict"] == "block"
    assert events[-1].payload["hook_event_name"] == "PreToolUse"


def test_permission_request_blocks_apply_patch_to_git_directory(tmp_path):
    spec = load_spec(tmp_path)

    result = handle_codex_hook(
        event_name="PermissionRequest",
        raw_input={
            "session_id": "session-1",
            "cwd": "/repo",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Update File: .git/config\n"},
        },
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        spec=spec,
    )

    assert result.exit_code == 2
    assert "protected path" in result.stdout


def test_post_tool_use_records_evidence_for_test_command(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    spec = load_spec(tmp_path)

    result = handle_codex_hook(
        event_name="PostToolUse",
        raw_input={
            "session_id": "session-1",
            "cwd": "/repo",
            "tool_name": "Bash",
            "tool_input": {"command": "uv run pytest -q"},
            "tool_output": {"exit_code": 0, "stdout": "46 passed"},
        },
        store=log,
        spec=spec,
    )

    assert result.exit_code == 0
    event_types = [event.event_type for event in log.read_all()]
    assert "evidence_registered" in event_types


def test_stop_requires_evidence_and_verification(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    spec = load_spec(tmp_path)

    result = handle_codex_hook(
        event_name="Stop",
        raw_input={"session_id": "session-1", "cwd": "/repo"},
        store=log,
        spec=spec,
    )

    assert result.exit_code == 2
    assert "Cannot stop yet" in result.stdout
    assert "record evidence" in result.stdout
    assert log.read_all()[-1].event_type == "stop_contract_failed"


def test_codex_hooks_drive_full_state_machine_to_done(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    spec = load_spec(tmp_path)
    session = {"session_id": "session-1", "cwd": "/repo"}

    handle_codex_hook("UserPromptSubmit", {**session, "prompt": "build feature X"}, log, spec)
    handle_codex_hook(
        "PostToolUse",
        {
            **session,
            "tool_name": "Bash",
            "tool_input": {"command": "uv run pytest -q"},
            "tool_output": {"exit_code": 0, "stdout": "46 passed"},
        },
        log,
        spec,
    )
    handle_codex_hook("UserPromptSubmit", {**session, "prompt": "verdict: PASS"}, log, spec)

    stop = handle_codex_hook("Stop", session, log, spec)

    assert stop.exit_code == 0
    assert json.loads(stop.stdout)["decision"] == "allow"

    transitions = [e for e in log.read_all() if e.event_type == "state_transitioned"]
    path = [(t.payload["from"], t.payload["event"], t.payload["to"]) for t in transitions]
    assert path == [
        ("backlog", "feature_selected", "building"),
        ("building", "evidence_recorded", "evidence_ready"),
        ("evidence_ready", "review_requested", "evaluating"),
        ("evaluating", "evaluator_passed", "done"),
    ]


def test_stop_blocks_when_state_machine_has_not_reached_terminal(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    spec = load_spec(tmp_path)
    session = {"session_id": "session-1", "cwd": "/repo"}

    # Kick off but do not record evidence or request review.
    handle_codex_hook("UserPromptSubmit", {**session, "prompt": "build feature X"}, log, spec)

    result = handle_codex_hook("Stop", session, log, spec)

    assert result.exit_code == 2
    assert "Cannot stop yet" in result.stdout
    assert log.read_all()[-1].event_type == "stop_contract_failed"


def test_changing_dsl_transitions_changes_hook_behavior(tmp_path):
    """Changing the loop transitions in hook-loop.json changes hook behavior:
    here evaluator_passed routes back to building (rework) instead of done, so
    Stop is blocked even after a full evidence + verdict sequence."""
    raw = software_delivery_dsl()
    # Reroute evaluator_passed from evaluating->done to evaluating->building.
    raw["loop"]["transitions"] = [
        {"from": "backlog", "event": "feature_selected", "to": "building"},
        {"from": "building", "event": "evidence_recorded", "to": "evidence_ready"},
        {"from": "evidence_ready", "event": "review_requested", "to": "evaluating"},
        {"from": "evaluating", "event": "evaluator_passed", "to": "building"},
    ]
    path = tmp_path / "loop.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    spec = load_loop_spec(path)
    log = JsonlEventLog(tmp_path / "events.jsonl")
    session = {"session_id": "session-1", "cwd": "/repo"}

    handle_codex_hook("UserPromptSubmit", {**session, "prompt": "build feature X"}, log, spec)
    handle_codex_hook(
        "PostToolUse",
        {
            **session,
            "tool_name": "Bash",
            "tool_input": {"command": "uv run pytest -q"},
            "tool_output": {"exit_code": 0, "stdout": "ok"},
        },
        log,
        spec,
    )
    handle_codex_hook("UserPromptSubmit", {**session, "prompt": "verdict: PASS"}, log, spec)

    stop = handle_codex_hook("Stop", session, log, spec)

    # The loop never reaches `done` because the DSL reroutes evaluator_passed
    # back to building, so Stop must block.
    assert stop.exit_code == 2
    assert "Cannot stop yet" in stop.stdout
    transitions = [e for e in log.read_all() if e.event_type == "state_transitioned"]
    assert transitions[-1].payload["to"] == "building"

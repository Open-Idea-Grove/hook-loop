import json

from hook_loop.codex_adapter import handle_codex_hook, normalize_codex_hook_input
from hook_loop.store import JsonlEventLog


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
    )

    assert result.exit_code == 2
    assert "risky action" in result.stdout
    events = log.read_all()
    assert events[-1].event_type == "hook_fired"
    assert events[-1].payload["verdict"] == "block"
    assert events[-1].payload["hook_event_name"] == "PreToolUse"


def test_permission_request_blocks_apply_patch_to_git_directory(tmp_path):
    result = handle_codex_hook(
        event_name="PermissionRequest",
        raw_input={
            "session_id": "session-1",
            "cwd": "/repo",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Update File: .git/config\n"},
        },
        store=JsonlEventLog(tmp_path / "events.jsonl"),
    )

    assert result.exit_code == 2
    assert "protected path" in result.stdout


def test_post_tool_use_records_evidence_for_test_command(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")

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
    )

    assert result.exit_code == 0
    event_types = [event.event_type for event in log.read_all()]
    assert "evidence_registered" in event_types


def test_stop_requires_evidence_and_verification(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")

    result = handle_codex_hook(
        event_name="Stop",
        raw_input={"session_id": "session-1", "cwd": "/repo"},
        store=log,
    )

    assert result.exit_code == 2
    assert "Cannot stop yet" in result.stdout
    assert "record evidence" in result.stdout
    assert log.read_all()[-1].event_type == "stop_contract_failed"


def test_stop_allows_when_evidence_verification_and_evaluator_pass_exist(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    for raw in [
        {
            "session_id": "session-1",
            "cwd": "/repo",
            "tool_name": "Bash",
            "tool_input": {"command": "uv run pytest -q"},
            "tool_output": {"exit_code": 0, "stdout": "46 passed"},
        },
        {
            "session_id": "session-1",
            "cwd": "/repo",
            "tool_name": "Bash",
            "tool_input": {"command": "git diff --check"},
            "tool_output": {"exit_code": 0, "stdout": ""},
        },
    ]:
        handle_codex_hook("PostToolUse", raw, log)
    handle_codex_hook(
        "UserPromptSubmit",
        {"session_id": "session-1", "cwd": "/repo", "prompt": "Evaluator verdict: PASS"},
        log,
    )

    result = handle_codex_hook("Stop", {"session_id": "session-1", "cwd": "/repo"}, log)

    assert result.exit_code == 0
    assert json.loads(result.stdout)["decision"] == "allow"

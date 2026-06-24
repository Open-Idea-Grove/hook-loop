import json

from hook_loop.cli import main
from hook_loop.dsl import load_loop_spec
from hook_loop.opencode_adapter import handle_opencode_hook, normalize_opencode_hook_input
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
        "codex": {
            "event_map": [
                {
                    "codex_event": "UserPromptSubmit",
                    "when": {"prompt_not_match": "(?i)verdict"},
                    "emit": "feature_selected",
                },
                {
                    "codex_event": "PostToolUse",
                    "when": {
                        "tool_name": "Bash",
                        "command_match": "pytest|test|lint|mypy|git diff --check",
                        "exit_code": 0,
                    },
                    "record": {
                        "event_type": "evidence_registered",
                        "actor": "codex",
                        "payload": {"kind": "verification"},
                        "include": ["command", "exit_code", "stdout"],
                    },
                    "emit": "evidence_recorded",
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
                },
                {
                    "codex_event": "UserPromptSubmit",
                    "when": {"prompt_match": "(?i)verdict.*PASS|PASS.*verdict"},
                    "emit": "evaluator_passed",
                    "guard_satisfied": ["evidence_bound_to_criteria"],
                },
            ]
        },
    }


def write_spec(tmp_path):
    path = tmp_path / "loop.json"
    path.write_text(json.dumps(software_delivery_dsl()), encoding="utf-8")
    return path


def load_spec(tmp_path):
    return load_loop_spec(write_spec(tmp_path))


def test_translates_opencode_tool_after_event_to_codex_post_tool_use():
    context = normalize_opencode_hook_input(
        "tool.execute.after",
        {
            "session_id": "session-1",
            "message_id": "message-1",
            "cwd": "/repo",
            "tool": "bash",
            "input": {"command": "uv run pytest -q"},
            "output": {"exit_code": 0, "stdout": "ok"},
        },
    )

    assert context.platform == "opencode"
    assert context.hook_event_name == "PostToolUse"
    assert context.event == "action_completed"
    assert context.session_id == "session-1"
    assert context.run_id == "message-1"
    assert context.cwd == "/repo"
    assert context.tool_name == "Bash"
    assert context.tool_input == {"command": "uv run pytest -q"}
    assert context.payload["tool_output"] == {"exit_code": 0, "stdout": "ok"}
    assert context.raw_input["opencode_event_name"] == "tool.execute.after"


def test_normalizes_lowercase_opencode_tool_names():
    cases = {
        "bash": "Bash",
        "write": "Write",
        "edit": "Edit",
        "read": "Read",
        "grep": "Grep",
        "glob": "Glob",
        "todo_write": "TodoWrite",
        "apply_patch": "apply_patch",
    }

    for opencode_name, codex_name in cases.items():
        context = normalize_opencode_hook_input("tool.execute.before", {"tool": opencode_name})
        assert context.tool_name == codex_name


def test_opencode_pre_tool_guardrail_blocks_risky_bash(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    result = handle_opencode_hook(
        "tool.execute.before",
        {
            "session_id": "session-1",
            "cwd": "/repo",
            "tool": "bash",
            "input": {"command": "rm -rf .git"},
        },
        log,
        load_spec(tmp_path),
    )

    assert result.exit_code == 2
    assert "risky action" in result.stdout
    event = log.read_all()[-1]
    assert event.event_type == "hook_fired"
    assert event.payload["platform"] == "opencode"
    assert event.payload["hook_event_name"] == "PreToolUse"
    assert event.payload["tool_name"] == "Bash"


def test_opencode_hooks_drive_full_state_machine_to_done(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    spec = load_spec(tmp_path)
    session = {"session_id": "session-1", "cwd": "/repo"}

    handle_opencode_hook("session.created", session, log, spec)
    handle_opencode_hook("message.updated", {**session, "text": "implement adapter support"}, log, spec)
    handle_opencode_hook(
        "tool.execute.after",
        {
            **session,
            "tool": "bash",
            "input": {"command": "uv run pytest -q"},
            "output": {"exit_code": 0, "stdout": "89 passed"},
        },
        log,
        spec,
    )
    handle_opencode_hook("message.updated", {**session, "text": "verdict: PASS"}, log, spec)

    stop = handle_opencode_hook("session.idle", session, log, spec)

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


def test_opencode_hook_cli_reads_stdin_and_delegates(tmp_path, capsys, monkeypatch):
    event_log = tmp_path / "events.jsonl"
    config = write_spec(tmp_path)
    monkeypatch.setattr(
        "sys.stdin",
        type(
            "FakeStdin",
            (),
            {
                "read": lambda self: json.dumps(
                    {
                        "session_id": "session-1",
                        "cwd": "/repo",
                        "tool": "bash",
                        "input": {"command": "rm -rf .git"},
                    }
                )
            },
        )(),
    )

    exit_code = main(
        [
            "opencode-hook",
            "--event",
            "tool.execute.before",
            "--config",
            str(config),
            "--event-log",
            str(event_log),
        ]
    )

    assert exit_code == 2
    assert "risky action" in capsys.readouterr().out
    assert "opencode" in event_log.read_text(encoding="utf-8")

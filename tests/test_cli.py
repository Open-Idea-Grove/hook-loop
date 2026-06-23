import json

from hook_loop.cli import main


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


def test_codex_hook_command_reads_stdin_and_blocks_risky_command(tmp_path, capsys, monkeypatch):
    path = tmp_path / "loop.json"
    event_log = tmp_path / "events.jsonl"
    path.write_text(json.dumps(valid_dsl()), encoding="utf-8")
    monkeypatch.setattr(
        "sys.stdin",
        type("FakeStdin", (), {"read": lambda self: json.dumps({
            "session_id": "session-1",
            "cwd": str(tmp_path),
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf .git"},
        })})(),
    )

    exit_code = main([
        "codex-hook",
        "--event",
        "PreToolUse",
        "--config",
        str(path),
        "--event-log",
        str(event_log),
    ])

    assert exit_code == 2
    assert "risky action" in capsys.readouterr().out
    assert "hook_fired" in event_log.read_text(encoding="utf-8")


def test_codex_install_dry_run_plans_without_writing(tmp_path, capsys):
    exit_code = main([
        "codex",
        "install",
        "--profile",
        "software_delivery",
        "--target",
        "directory",
        "--destination",
        str(tmp_path),
    ])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "planned:" in out
    assert ".codex/hooks.json" in out
    assert not (tmp_path / ".codex").exists()


def test_codex_install_directory_writes_scaffold(tmp_path, capsys):
    exit_code = main([
        "codex",
        "install",
        "--profile",
        "software_delivery",
        "--target",
        "directory",
        "--destination",
        str(tmp_path),
        "--write",
    ])

    assert exit_code == 0
    assert "written:" in capsys.readouterr().out
    assert (tmp_path / ".codex" / "hooks.json").exists()
    assert (tmp_path / "hook-loop.json").exists()
    assert not (tmp_path / ".codex" / "hooks" / "hook_loop_codex.py").exists()


def test_codex_install_with_dsl_embeds_custom_loop(tmp_path, capsys):
    custom = {
        "loop": {
            "id": "approval_loop",
            "initial_state": "draft",
            "states": ["draft", "reviewing", "accepted", "stopped"],
            "terminal_states": ["accepted", "stopped"],
            "stop_state": "stopped",
            "events": ["submit", "approval_granted"],
            "transitions": [
                {"from": "draft", "event": "submit", "to": "reviewing"},
                {"from": "reviewing", "event": "approval_granted", "to": "accepted"},
            ],
        },
        "codex": {
            "event_map": [
                {"codex_event": "UserPromptSubmit", "when": {"prompt_match": "(?i)submit"}, "emit": "submit"}
            ]
        },
    }
    dsl_path = tmp_path / "custom.json"
    dsl_path.write_text(json.dumps(custom), encoding="utf-8")
    dest = tmp_path / "out"

    exit_code = main([
        "codex", "install",
        "--profile", "custom",
        "--target", "directory",
        "--destination", str(dest),
        "--dsl", str(dsl_path),
        "--write",
    ])

    assert exit_code == 0
    assert "written:" in capsys.readouterr().out
    embedded = json.loads((dest / "hook-loop.json").read_text(encoding="utf-8"))
    assert embedded["loop"]["id"] == "approval_loop"
    assert (dest / ".codex" / "hooks.json").exists()


def test_codex_install_with_invalid_dsl_reports_error(tmp_path, capsys):
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")

    exit_code = main([
        "codex", "install",
        "--profile", "custom",
        "--target", "directory",
        "--destination", str(tmp_path / "out"),
        "--dsl", str(broken),
        "--write",
    ])

    assert exit_code == 1
    assert "invalid:" in capsys.readouterr().err

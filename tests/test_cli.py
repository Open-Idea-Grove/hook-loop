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

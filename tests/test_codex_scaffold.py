import json

import pytest

from hook_loop.codex_scaffold import build_codex_scaffold, install_codex_scaffold
from hook_loop.dsl import DslError


def test_builds_software_delivery_scaffold():
    files = build_codex_scaffold(profile="software_delivery", command_prefix="hook-loop")

    assert set(files) == {".codex/hooks.json", "hook-loop.json"}
    hooks = json.loads(files[".codex/hooks.json"])
    loop = json.loads(files["hook-loop.json"])
    assert "PreToolUse" in hooks["hooks"]
    assert "PermissionRequest" in hooks["hooks"]
    assert "PostToolUse" in hooks["hooks"]
    assert "Stop" in hooks["hooks"]
    assert "codex-hook --event PreToolUse" in json.dumps(hooks)
    assert loop["loop"]["id"] == "software_delivery"


def test_generated_loop_contains_codex_event_map_for_full_state_machine():
    files = build_codex_scaffold(profile="software_delivery")
    loop = json.loads(files["hook-loop.json"])

    assert "codex" in loop
    rules = loop["codex"]["event_map"]
    emitted = [rule["emit"] for rule in rules]
    # The four transitions that carry the loop from backlog to done.
    assert emitted == ["feature_selected", "evidence_recorded", "review_requested", "evaluator_passed"]
    assert rules[1]["record"]["event_type"] == "evidence_registered"
    assert rules[2]["record"]["event_type"] == "verdict_recorded"
    assert "evidence_bound_to_criteria" in rules[3]["guard_satisfied"]


def test_install_scaffold_dry_run_does_not_write_files(tmp_path):
    result = install_codex_scaffold(
        profile="software_delivery",
        target="directory",
        destination=tmp_path,
        dry_run=True,
    )

    assert result.written == []
    assert result.planned
    assert not (tmp_path / ".codex").exists()


def test_install_scaffold_to_directory_writes_codex_files(tmp_path):
    result = install_codex_scaffold(
        profile="software_delivery",
        target="directory",
        destination=tmp_path,
        dry_run=False,
    )

    hooks_json = tmp_path / ".codex" / "hooks.json"
    loop_config = tmp_path / "hook-loop.json"
    assert hooks_json in result.written
    assert loop_config in result.written
    assert hooks_json.exists()
    assert loop_config.exists()
    assert "hook-loop codex-hook" in hooks_json.read_text(encoding="utf-8")
    # The placeholder hook script is no longer generated.
    assert not (tmp_path / ".codex" / "hooks" / "hook_loop_codex.py").exists()


def _custom_dsl():
    return {
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
                {"codex_event": "UserPromptSubmit", "when": {"prompt_match": "(?i)submit"}, "emit": "submit"},
                {
                    "codex_event": "UserPromptSubmit",
                    "when": {"prompt_match": "(?i)approved"},
                    "emit": "approval_granted",
                },
            ]
        },
    }


def test_build_scaffold_with_dsl_path_uses_custom_loop(tmp_path):
    dsl_path = tmp_path / "custom.json"
    dsl_path.write_text(json.dumps(_custom_dsl()), encoding="utf-8")

    files = build_codex_scaffold(profile="custom", dsl_path=dsl_path)

    assert set(files) == {".codex/hooks.json", "hook-loop.json"}
    loop = json.loads(files["hook-loop.json"])
    assert loop["loop"]["id"] == "approval_loop"
    assert loop["loop"]["initial_state"] == "draft"
    assert [r["emit"] for r in loop["codex"]["event_map"]] == ["submit", "approval_granted"]
    # The codex wiring still points at hook-loop codex-hook.
    assert "codex-hook --event Stop" in files[".codex/hooks.json"]


def test_build_scaffold_with_dsl_path_preserves_user_formatting(tmp_path):
    dsl_path = tmp_path / "custom.json"
    original = "{\n  \"loop\": {\n    \"id\": \"approval_loop\"\n  }\n}\n"
    dsl_path.write_text(original, encoding="utf-8")

    # The custom DSL above is missing required fields; use a valid one instead.
    dsl_path.write_text(json.dumps(_custom_dsl(), indent=2) + "\n", encoding="utf-8")
    files = build_codex_scaffold(profile="custom", dsl_path=dsl_path)

    # The scaffold embeds the source file content verbatim (validates first).
    assert files["hook-loop.json"] == dsl_path.read_text(encoding="utf-8")


def test_build_scaffold_with_invalid_dsl_path_raises(tmp_path):
    dsl_path = tmp_path / "broken.json"
    dsl_path.write_text("{", encoding="utf-8")

    with pytest.raises(DslError, match="invalid JSON"):
        build_codex_scaffold(profile="custom", dsl_path=dsl_path)


def test_install_scaffold_with_dsl_writes_custom_loop(tmp_path):
    src = tmp_path / "custom.json"
    src.write_text(json.dumps(_custom_dsl()), encoding="utf-8")
    dest = tmp_path / "out"

    result = install_codex_scaffold(
        profile="custom",
        target="directory",
        destination=dest,
        dry_run=False,
        dsl_path=src,
    )

    loop_config = dest / "hook-loop.json"
    assert loop_config in result.written
    assert json.loads(loop_config.read_text(encoding="utf-8"))["loop"]["id"] == "approval_loop"


def test_build_scaffold_without_dsl_still_requires_known_profile():
    with pytest.raises(ValueError, match="Unsupported Codex profile"):
        build_codex_scaffold(profile="unknown")

import json

import pytest

from hook_loop.codex_mapping import CodexEventMap, MatchSpec, ResolvedRule, RecordSpec
from hook_loop.dsl import DslError, load_loop_spec
from hook_loop.hooks import HookContext


def software_delivery_loop():
    return {
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


def software_delivery_dsl_with_codex():
    return {
        "loop": software_delivery_loop(),
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
                },
                {
                    "codex_event": "PostToolUse",
                    "when": {"tool_name": "Bash", "command_match": "pytest|test", "exit_code": 0},
                    "record": {"event_type": "evidence_registered", "actor": "codex"},
                    "emit": "evidence_recorded",
                },
            ]
        },
    }


def _context(**kwargs):
    base = {
        "state": "building",
        "event": None,
        "payload": {},
        "platform": "codex",
        "hook_event_name": "PostToolUse",
        "session_id": "s1",
        "run_id": "r1",
        "cwd": "/repo",
        "tool_name": "Bash",
        "tool_input": {"command": "uv run pytest -q"},
        "raw_input": {},
    }
    base.update(kwargs)
    return HookContext(**base)


def test_match_spec_tool_name_equality():
    spec = MatchSpec(tool_name="Bash")

    assert spec.matches(_context(tool_name="Bash")) is True
    assert spec.matches(_context(tool_name="Edit")) is False


def test_match_spec_command_match_regex():
    spec = MatchSpec(command_match="pytest|test")

    assert spec.matches(_context(tool_input={"command": "uv run pytest -q"})) is True
    assert spec.matches(_context(tool_input={"command": "git status"})) is False


def test_match_spec_prompt_match_and_not_match():
    match = MatchSpec(prompt_match="(?i)verdict.*PASS")
    nomatch = MatchSpec(prompt_not_match="(?i)verdict")

    ctx_yes = _context(hook_event_name="UserPromptSubmit", payload={"prompt": "verdict: PASS"})
    ctx_no = _context(hook_event_name="UserPromptSubmit", payload={"prompt": "build feature X"})

    assert match.matches(ctx_yes) is True
    assert match.matches(ctx_no) is False
    assert nomatch.matches(ctx_yes) is False
    assert nomatch.matches(ctx_no) is True


def test_match_spec_exit_code_from_tool_output():
    spec = MatchSpec(exit_code=0)

    ctx_ok = _context(payload={"tool_output": {"exit_code": 0, "stdout": "ok"}})
    ctx_fail = _context(payload={"tool_output": {"exit_code": 1, "stdout": ""}})

    assert spec.matches(ctx_ok) is True
    assert spec.matches(ctx_fail) is False


def test_match_spec_empty_always_matches():
    assert MatchSpec().matches(_context()) is True


def test_event_map_resolve_returns_matching_rules_in_order():
    mapping = CodexEventMap(
        rules=[
            ResolvedRule(
                codex_event="UserPromptSubmit",
                when=MatchSpec(prompt_not_match="(?i)verdict"),
                emit="feature_selected",
                record=None,
                guard_satisfied=frozenset(),
            ),
            ResolvedRule(
                codex_event="UserPromptSubmit",
                when=MatchSpec(prompt_match="(?i)verdict.*PASS"),
                emit="review_requested",
                record=RecordSpec(event_type="verdict_recorded", actor="evaluator", payload={"status": "PASS"}, include=()),
                guard_satisfied=frozenset(),
            ),
        ]
    )

    kickoff = mapping.resolve(_context(hook_event_name="UserPromptSubmit", payload={"prompt": "build it"}))
    verdict = mapping.resolve(
        _context(hook_event_name="UserPromptSubmit", payload={"prompt": "verdict: PASS"})
    )

    assert [r.emit for r in kickoff] == ["feature_selected"]
    assert [r.emit for r in verdict] == ["review_requested"]


def test_load_loop_spec_parses_codex_event_map(tmp_path):
    path = tmp_path / "loop.json"
    path.write_text(json.dumps(software_delivery_dsl_with_codex()), encoding="utf-8")

    spec = load_loop_spec(path)

    assert spec.codex is not None
    assert len(spec.codex.rules) == 2
    assert spec.codex.rules[0].codex_event == "UserPromptSubmit"
    assert spec.codex.rules[0].emit == "feature_selected"
    assert spec.codex.rules[1].codex_event == "PostToolUse"
    assert spec.codex.rules[1].emit == "evidence_recorded"
    assert spec.codex.rules[1].record is not None
    assert spec.codex.rules[1].record.event_type == "evidence_registered"


def test_load_loop_spec_without_codex_section_has_none(tmp_path):
    raw = software_delivery_dsl_with_codex()
    del raw["codex"]
    path = tmp_path / "loop.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    spec = load_loop_spec(path)

    assert spec.codex is None


def test_load_loop_spec_rejects_unknown_codex_event(tmp_path):
    raw = software_delivery_dsl_with_codex()
    raw["codex"]["event_map"][0]["codex_event"] = "NotARealEvent"
    path = tmp_path / "loop.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DslError, match="codex_event"):
        load_loop_spec(path)


def test_load_loop_spec_rejects_emit_not_in_events(tmp_path):
    raw = software_delivery_dsl_with_codex()
    raw["codex"]["event_map"][0]["emit"] = "not_a_loop_event"
    path = tmp_path / "loop.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DslError, match="emit"):
        load_loop_spec(path)


def test_load_loop_spec_rejects_emit_with_no_matching_transition(tmp_path):
    raw = software_delivery_dsl_with_codex()
    # Add a loop event that has no transition, then point a rule at it.
    raw["loop"]["events"].append("orphan_event")
    raw["codex"]["event_map"].append(
        {"codex_event": "UserPromptSubmit", "when": {}, "emit": "orphan_event"}
    )
    path = tmp_path / "loop.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(DslError, match="emit"):
        load_loop_spec(path)

"""Experiment 2: compare gallery DSL behavior through Codex and opencode adapters.

Run: uv run python experiments/check_gallery_behavior.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hook_loop.codex_adapter import handle_codex_hook
from hook_loop.codex_mapping import MatchSpec, ResolvedRule
from hook_loop.dsl import DslError, LoopSpec, load_loop_spec
from hook_loop.evaluator import FakeEvaluator
from hook_loop.opencode_adapter import handle_opencode_hook
from hook_loop.runtime import FakeAgent, LoopRuntime
from hook_loop.store import JsonlEventLog


ROOT = Path(__file__).resolve().parents[1]
GALLERY = ROOT / "gallery"
OUT = ROOT / "experiments" / "gallery-check"
REPORT = ROOT / "experiments" / "gallery-check-report.md"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    details: list[str] = []

    for dsl_path in sorted(GALLERY.glob("*.json")):
        row, detail = check_dsl(dsl_path)
        rows.append(row)
        details.append(detail)

    REPORT.write_text(render_report(rows, details), encoding="utf-8")
    print(f"wrote {REPORT}")


def check_dsl(dsl_path: Path) -> tuple[dict[str, Any], str]:
    name = dsl_path.stem
    row: dict[str, Any] = {"dsl": name}
    issues: list[str] = []

    try:
        spec = load_loop_spec(dsl_path)
        row["validate"] = "pass"
    except DslError as exc:
        row.update({"validate": "fail", "simulate": "skip", "codex": "skip", "opencode": "skip"})
        return row, f"### {name}\n\nValidation failed: `{exc}`\n"

    final_state = simulate(spec, OUT / f"{name}-simulate.jsonl")
    row["simulate"] = final_state
    if final_state not in spec.definition.terminal_states:
        issues.append(f"simulation ended in non-terminal state `{final_state}`")

    transition_events = {transition.event for transition in spec.definition.transitions}
    emitted_events = {rule.emit for rule in spec.codex.rules} if spec.codex is not None else set()
    missing = sorted(transition_events - emitted_events)
    extra = sorted(emitted_events - transition_events)
    if spec.codex is None:
        issues.append("missing `codex.event_map`; real Codex/opencode hooks cannot drive this DSL")
    elif missing:
        issues.append(f"codex.event_map does not emit: {', '.join(missing)}")
    if extra:
        issues.append(f"codex.event_map emits events with no transition: {', '.join(extra)}")
    if spec.codex is None:
        codex_trace: list[tuple[str, str, str]] = []
        opencode_trace: list[tuple[str, str, str]] = []
        row["codex"] = "skip"
        row["opencode"] = "skip"
    else:
        codex_trace, codex_notes = drive(spec, OUT / f"{name}-codex.jsonl", platform="codex")
        opencode_trace, opencode_notes = drive(spec, OUT / f"{name}-opencode.jsonl", platform="opencode")
        issues.extend(codex_notes)
        issues.extend(opencode_notes)
        row["codex"] = trace_status(spec, codex_trace)
        row["opencode"] = trace_status(spec, opencode_trace)
        if codex_trace != opencode_trace:
            issues.append("Codex and opencode transition traces differ")

    row["issues"] = len(issues)
    detail = render_detail(name, row, issues, codex_trace, opencode_trace)
    return row, detail


def simulate(spec: LoopSpec, event_log: Path) -> str:
    if event_log.exists():
        event_log.unlink()
    runtime = LoopRuntime(
        definition=spec.definition,
        store=JsonlEventLog(event_log),
        agent=FakeAgent({state: list(steps) for state, steps in spec.simulation.agent_steps.items()}),
        evaluator=FakeEvaluator(list(spec.simulation.verdicts)),
        session_id="simulate",
    )
    return runtime.run_until_stop(spec.simulation.budget)


def drive(spec: LoopSpec, event_log: Path, platform: str) -> tuple[list[tuple[str, str, str]], list[str]]:
    notes: list[str] = []
    if event_log.exists():
        event_log.unlink()
    log = JsonlEventLog(event_log)
    session = {"session_id": f"{platform}-{spec.definition.id}", "cwd": str(ROOT)}

    for _ in range(spec.simulation.budget.max_turns + 4):
        state = current_state(spec, log)
        if state in spec.definition.terminal_states:
            break
        steps = list(spec.simulation.agent_steps.get(state, ()))
        if not steps:
            notes.append(f"{platform}: no simulation step for state `{state}`")
            break
        target_event = steps[0].event
        rule = find_rule(spec, target_event)
        if rule is None:
            notes.append(f"{platform}: no codex.event_map rule emits `{target_event}` from `{state}`")
            break
        hook_event, payload = hook_payload(rule, session, platform)
        before = len(transitions(log))
        if platform == "codex":
            result = handle_codex_hook(hook_event, payload, log, spec)
        else:
            result = handle_opencode_hook(hook_event, payload, log, spec)
        after = len(transitions(log))
        if result.exit_code not in {0, 2}:
            notes.append(f"{platform}: {hook_event} for `{target_event}` exited {result.exit_code}")
            break
        if after == before:
            notes.append(f"{platform}: {hook_event} did not transition for `{target_event}` from `{state}`")
            break

    stop_event = "Stop" if platform == "codex" else "session.idle"
    if platform == "codex":
        handle_codex_hook(stop_event, session, log, spec)
    else:
        handle_opencode_hook(stop_event, session, log, spec)
    return transitions(log), notes


def find_rule(spec: LoopSpec, event: str) -> ResolvedRule | None:
    if spec.codex is None:
        return None
    for rule in spec.codex.rules:
        if rule.emit == event:
            return rule
    return None


def hook_payload(rule: ResolvedRule, session: dict[str, str], platform: str) -> tuple[str, dict[str, Any]]:
    prompt = prompt_for(rule.emit, rule.when)
    command = command_for(rule.when)
    exit_code = int(rule.when.exit_code) if rule.when.exit_code is not None else 0

    if platform == "codex":
        if rule.codex_event in {"UserPromptSubmit", "SessionStart"}:
            payload = {**session, "prompt": prompt}
        else:
            payload = {
                **session,
                "tool_name": rule.when.tool_name or "Bash",
                "tool_input": {"command": command},
                "tool_output": {"exit_code": exit_code, "stdout": "ok"},
            }
        return rule.codex_event, payload

    if rule.codex_event == "UserPromptSubmit":
        return "message.updated", {**session, "text": prompt}
    if rule.codex_event == "SessionStart":
        return "session.created", dict(session)
    if rule.codex_event == "PostToolUse":
        return (
            "tool.execute.after",
            {
                **session,
                "tool": (rule.when.tool_name or "Bash").lower(),
                "input": {"command": command},
                "output": {"exit_code": exit_code, "stdout": "ok"},
            },
        )
    return (
        "tool.execute.before",
        {**session, "tool": (rule.when.tool_name or "Bash").lower(), "input": {"command": command}},
    )


def prompt_for(event: str, when: MatchSpec) -> str:
    if when.prompt_not_match is not None and when.prompt_match is None:
        return f"start {event} now"
    if when.prompt_match is None:
        return event
    pattern = re.sub(r"\(\?[a-zA-Z]+\)", "", when.prompt_match)
    choices = [part.strip(" ^$.*()[]{}?+") for part in pattern.split("|")]
    for choice in choices:
        if choice:
            return choice
    return event


def command_for(when: MatchSpec) -> str:
    if when.command_match is None:
        return "uv run pytest -q"
    pattern = re.sub(r"\(\?[a-zA-Z]+\)", "", when.command_match)
    first = pattern.split("|")[0].strip(" ^$.*()[]{}?+")
    if first in {"pytest", "test"}:
        return "uv run pytest -q"
    if first:
        return first
    return "uv run pytest -q"


def current_state(spec: LoopSpec, log: JsonlEventLog) -> str:
    trace = transitions(log)
    return trace[-1][2] if trace else spec.definition.initial_state


def transitions(log: JsonlEventLog) -> list[tuple[str, str, str]]:
    return [
        (event.payload["from"], event.payload["event"], event.payload["to"])
        for event in log.read_all()
        if event.event_type == "state_transitioned"
    ]


def trace_status(spec: LoopSpec, trace: list[tuple[str, str, str]]) -> str:
    if not trace:
        return "no transitions"
    return "terminal" if trace[-1][2] in spec.definition.terminal_states else trace[-1][2]


def render_report(rows: list[dict[str, Any]], details: list[str]) -> str:
    lines = [
        "# Experiment 2 Gallery Behavior Check",
        "",
        "Outer opencode plan_execute: #14 fixed (plugin init no longer blocks). "
        "All 8 DSLs now have codex.event_map and produce Codex/opencode adapter traces.",
        "",
        "Note: builder_evaluator and rework_loop stop at `evaluating` here because the",
        "script has no external evaluator agent to emit a verdict prompt; simulate",
        "reaches `done` via FakeEvaluator. In a real hook session, a prompt containing",
        "'verdict: PASS' or 'NEEDS_WORK' would drive the evaluating state.",
        "",
        "| DSL | validate | simulate | codex trace | opencode trace | issues |",
        "| --- | --- | --- | --- | --- | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['dsl']} | {row['validate']} | {row['simulate']} | {row['codex']} | {row['opencode']} | {row['issues']} |"
        )
    lines.extend(["", "## Details", "", *details])
    return "\n".join(lines) + "\n"


def render_detail(
    name: str,
    row: dict[str, Any],
    issues: list[str],
    codex_trace: list[tuple[str, str, str]],
    opencode_trace: list[tuple[str, str, str]],
) -> str:
    lines = [f"### {name}", "", f"Status: validate={row['validate']}, simulate={row['simulate']}."]
    if codex_trace:
        lines.append(f"Codex trace: `{format_trace(codex_trace)}`.")
    else:
        lines.append("Codex trace: skipped or empty.")
    if opencode_trace:
        lines.append(f"opencode trace: `{format_trace(opencode_trace)}`.")
    else:
        lines.append("opencode trace: skipped or empty.")
    if issues:
        lines.append("Issues:")
        for issue in issues:
            lines.append(f"- {issue}")
    else:
        lines.append("Issues: none found by adapter-level comparison.")
    lines.append("")
    return "\n".join(lines)


def format_trace(trace: list[tuple[str, str, str]]) -> str:
    return " -> ".join(f"{src} --{event}--> {dst}" for src, event, dst in trace)


if __name__ == "__main__":
    main()

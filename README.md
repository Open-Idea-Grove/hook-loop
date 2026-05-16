# hook-loop

`hook-loop` is a platform-neutral experiment for building autonomous agent outer loops from explicit state machines and hook points.

The current implementation is the B-stage runtime described in:

- [Design spec](docs/superpowers/specs/2026-05-16-hook-loop-agent-design.md)
- [Runtime implementation plan](docs/superpowers/plans/2026-05-16-hook-loop-runtime-plan.md)

It does not implement the later DSL/code generator stage yet. The runtime is intentionally small and deterministic so loop behavior can be tested without a real LLM.

## What Is Implemented

- Schema loading and validation for loop definitions.
- Guard-aware state transitions.
- Append-only JSONL event log with session-aware recovery.
- In-process hook bus with allow/block/steer decisions.
- Machine-readable evaluator verdict parsing.
- Minimal fake-agent runtime simulation for pass, rework, stop, resume, and hook-block flows.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for Python environment and dependency management

The project uses a `src/` layout and pytest is declared in the uv dev dependency group.

## Verify The Work

From the repository root:

```bash
uv sync
uv run pytest -q
```

Expected result:

```text
30 passed
```

You can also run focused checks:

```bash
uv run pytest tests/test_state_machine.py -q
uv run pytest tests/test_event_store.py -q
uv run pytest tests/test_hooks.py -q
uv run pytest tests/test_evaluator.py -q
uv run pytest tests/test_runtime_simulation.py -q
```

## Minimal Runtime Example

```python
from hook_loop import AgentStep, FakeAgent, FakeEvaluator, JsonlEventLog
from hook_loop import LoopDefinition, LoopRuntime, RuntimeBudget, Verdict


definition = LoopDefinition.from_dict(
    {
        "id": "software_delivery",
        "initial_state": "backlog",
        "states": ["backlog", "building", "evidence_ready", "evaluating", "done", "stopped"],
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

runtime = LoopRuntime(
    definition=definition,
    store=JsonlEventLog("events.jsonl"),
    agent=FakeAgent(
        {
            "backlog": [AgentStep("feature_selected")],
            "building": [AgentStep("evidence_recorded", {"evidence_id": "e1"})],
            "evidence_ready": [AgentStep("review_requested")],
        }
    ),
    evaluator=FakeEvaluator([Verdict("PASS", "evidence checked")]),
)

assert runtime.run_until_stop(RuntimeBudget(max_turns=3)) == "done"
```

## Current Boundaries

- No Codex, Claude Code, or pi adapter is included yet.
- No generated DSL parser is included yet.
- Hook callbacks are in-process contracts, not a security boundary.
- `FakeAgent` and `FakeEvaluator` exist to make loop semantics deterministic in tests.

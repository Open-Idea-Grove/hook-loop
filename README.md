# hook-loop

`hook-loop` is a platform-neutral experiment for building autonomous agent outer loops from explicit state machines and hook points.

The current implementation is the B-stage runtime described in:

- [Design spec](docs/superpowers/specs/2026-05-16-hook-loop-agent-design.md)
- [Runtime implementation plan](docs/superpowers/plans/2026-05-16-hook-loop-runtime-plan.md)

It implements the B-stage runtime plus a minimal C-stage JSON DSL and CLI path. It does not implement generated platform adapters yet. The runtime is intentionally small and deterministic so loop behavior can be tested without a real LLM.

## What Is Implemented

- Schema loading and validation for loop definitions.
- Guard-aware state transitions.
- Append-only JSONL event log with session-aware recovery.
- In-process hook bus with allow/block/steer decisions.
- Machine-readable evaluator verdict parsing.
- Minimal fake-agent runtime simulation for pass, rework, stop, resume, and hook-block flows.
- JSON DSL loading from `examples/software_delivery.json`.
- `hook-loop validate` and `hook-loop simulate` CLI commands.
- Codex-first hook adapter for the software delivery quality loop.
- `hook-loop codex-hook` for Codex command hooks.
- `hook-loop codex install` scaffold generation with dry-run by default.

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
46 passed
```

You can also run focused checks:

```bash
uv run pytest tests/test_state_machine.py -q
uv run pytest tests/test_event_store.py -q
uv run pytest tests/test_hooks.py -q
uv run pytest tests/test_evaluator.py -q
uv run pytest tests/test_runtime_simulation.py -q
uv run pytest tests/test_dsl.py -q
uv run pytest tests/test_cli.py -q
```

## JSON DSL

The canonical example is [examples/software_delivery.json](examples/software_delivery.json). It contains:

- `loop`: states, terminal states, stop state, events, and transitions.
- `simulation`: deterministic fake-agent steps, evaluator verdicts, and runtime budget.

Validate it with:

```bash
uv run hook-loop validate examples/software_delivery.json
```

Expected output:

```text
valid: software_delivery
```

Run the deterministic simulation with:

```bash
uv run hook-loop simulate examples/software_delivery.json --event-log /private/tmp/hook-loop-example.jsonl
```

Expected output includes:

```text
final_state: done
```

## Codex Hook Adapter

The Codex adapter is a first MVP for using `hook-loop` patterns inside Codex
hooks without making the repository root load active hooks during development.

Preview the generated software delivery hook scaffold:

```bash
uv run hook-loop codex install \
  --profile software_delivery \
  --target directory \
  --destination /tmp/hook-loop-codex-preview
```

Write the scaffold only when you explicitly opt in:

```bash
uv run hook-loop codex install \
  --profile software_delivery \
  --target directory \
  --destination /tmp/hook-loop-codex-preview \
  --write
```

The generated scaffold contains:

- `.codex/hooks.json`
- `.codex/hooks/hook_loop_codex.py`
- `hook-loop.json`

The hook command entrypoint is:

```bash
uv run hook-loop codex-hook \
  --event PreToolUse \
  --config hook-loop.json \
  --event-log .hook-loop/events.jsonl
```

The first profile focuses on software delivery:

- `PreToolUse` / `PermissionRequest` block risky shell and protected-path writes.
- `PostToolUse` records verification evidence from commands such as tests and
  `git diff --check`.
- `Stop` requires evidence, verification, and a fresh evaluator `PASS` before
  allowing the agent to finish.

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
- No generated hook scaffold is included yet.
- Hook callbacks are in-process contracts, not a security boundary.
- `FakeAgent` and `FakeEvaluator` exist to make loop semantics deterministic in tests.

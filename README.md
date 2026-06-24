# hook-loop

`hook-loop` makes autonomous agent outer loops **explicit**: you write a state machine in JSON, and hook-loop wires it into platform hooks (Codex / opencode) so the agent is gated by the loop at every step — it cannot stop until the state machine reaches a terminal state.

## Basic Usage

### 1. Install

```bash
uv sync                          # install hook-loop into .venv
```

### 2. Write a DSL

A hook-loop DSL is a single JSON file with three sections: `loop`, `simulation`, and `codex`.

```jsonc
// my-loop.json
{
  "loop": {
    "id": "plan_execute",
    "initial_state": "backlog",
    "states": ["backlog", "planning", "executing", "verifying", "done", "stopped"],
    "terminal_states": ["done", "stopped"],
    "stop_state": "stopped",
    "events": ["kickoff", "plan_ready", "step_done", "all_steps_pass"],
    "transitions": [
      {"from": "backlog", "event": "kickoff", "to": "planning"},
      {"from": "planning", "event": "plan_ready", "to": "executing"},
      {"from": "executing", "event": "step_done", "to": "verifying"},
      {"from": "verifying", "event": "all_steps_pass", "to": "done", "guards": ["plan_complete"]}
    ]
  },
  "simulation": {
    "budget": {"max_turns": 6, "max_no_progress_turns": 2},
    "agent_steps": {
      "backlog": [{"event": "kickoff"}],
      "planning": [{"event": "plan_ready"}],
      "executing": [{"event": "step_done"}],
      "verifying": [{"event": "all_steps_pass"}]
    },
    "verdicts": [{"status": "PASS", "details": "all steps verified"}]
  },
  "codex": {
    "event_map": [
      {"codex_event": "SessionStart", "emit": "kickoff"},
      {"codex_event": "PostToolUse", "when": {"tool_name": "Write", "exit_code": 0}, "emit": "plan_ready"},
      {"codex_event": "PostToolUse", "when": {"tool_name": "Bash", "command_match": "pytest|test", "exit_code": 0}, "emit": "step_done"},
      {"codex_event": "UserPromptSubmit", "when": {"prompt_match": "(?i)all steps pass"}, "emit": "all_steps_pass", "guard_satisfied": ["plan_complete"]}
    ]
  }
}
```

**DSL structure:**

| Section | What it does |
|---|---|
| `loop` | The state machine: states, events, transitions, terminal states. Guards gate specific transitions. |
| `simulation` | Deterministic test harness: fake agent steps + verdicts + budget. Lets you validate loop semantics without a real LLM. |
| `codex.event_map` | Maps platform hook events to loop transitions. Each rule has a `codex_event`, optional `when` matchers, and an `emit` (loop event to fire). `record` side-effects append evidence before firing. `guard_satisfied` self-declares guards. |

**`when` matchers** (all optional, logical AND):

- `tool_name` — exact tool name (`"Bash"`, `"Write"`, `"Edit"`, ...).
- `command_match` — regex searched against the Bash command string.
- `prompt_match` / `prompt_not_match` — regex against user prompt text.
- `exit_code` — tool exit code (as integer).

### 3. Validate & simulate

```bash
uv run hook-loop validate my-loop.json        # → valid: plan_execute
uv run hook-loop simulate my-loop.json         # → final_state: done
```

### 4. Use with Codex

Generate the hook scaffold (Codex `hooks.json` + embedded DSL):

```bash
uv run hook-loop codex install \
  --profile plan_execute \
  --dsl my-loop.json \
  --destination . \
  --write
```

This creates `.codex/hooks.json` and `hook-loop.json` in your project. Codex 0.142+ reads hooks from `CODEX_HOME` (default `~/.codex/`). To keep hooks project-level without touching your global config, set `CODEX_HOME` to an in-project directory:

```bash
mkdir -p .codex-home
cp .codex/hooks.json .codex-home/hooks.json
ln -sf ~/.codex/auth.json .codex-home/auth.json   # read-only ref, no credentials copied
cp ~/.codex/config.toml .codex-home/config.toml

# Absolute path to hook-loop (hook subprocess may not have .venv on PATH):
HOOK_BIN="$(pwd)/.venv/bin/hook-loop"
sed -i "s|hook-loop |$HOOK_BIN |g" .codex-home/hooks.json
```

Then run codex with that home:

```bash
CODEX_HOME=$PWD/.codex-home codex exec \
  --skip-git-repo-check \
  --dangerously-bypass-approvals-and-sandbox \
  --dangerously-bypass-hook-trust \
  -C . \
  "implement feature X and verify with pytest" \
  --json
```

Check the loop state machine trace:

```bash
cat .hook-loop/events.jsonl
```

### 5. Use with opencode

Generate the opencode plugin scaffold:

```bash
uv run hook-loop opencode install \
  --profile plan_execute \
  --dsl my-loop.json \
  --destination . \
  --write
```

This creates:
- `.opencode/plugins/hook_loop.js` — a JS plugin that bridges opencode events to `hook-loop opencode-hook`
- `hook-loop.json` — your embedded DSL

opencode loads the plugin automatically. The plugin translates opencode events (`tool.execute.before` → `PreToolUse`, `tool.execute.after` → `PostToolUse`, `session.idle` → `Stop`, `message.updated` → `UserPromptSubmit`) and shells out to `hook-loop opencode-hook`.

Run an opencode agent:

```bash
opencode run "implement feature X and verify with pytest"
```

Evidence and state transitions are logged to `.hook-loop/events.jsonl`.

### How it works

```
                          hook-loop.json
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
  codex.event_map        loop states          simulation
        │                + transitions          (test only)
        │                      │
   ┌────┴────┐          EventSourcedLoopDriver
   │ Codex   │              (state machine
   │ hooks   │               recovery + gating)
   └────┬────┘                  │        ┌─────┴─────┐
        │                       │        │ Stop gate │
        │              .hook-loop/events.jsonl └─────┘
        │
  .opencode/plugins/hook_loop.js
```

Every hook call recovers the current state from the event log, checks event_map rules, applies matching transitions, and records the result. `PreToolUse` guards risky commands. `Stop` blocks until a terminal state is reached.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for Python environment and dependency management

## What Is Implemented

- Schema loading and validation for loop definitions.
- Guard-aware state transitions.
- Append-only JSONL event log with session-aware recovery.
- In-process hook bus with allow/block/steer decisions.
- Machine-readable evaluator verdict parsing.
- Minimal fake-agent runtime simulation for pass, rework, stop, resume, and hook-block flows.
- `hook-loop validate` and `hook-loop simulate` CLI commands.
- Codex hook adapter driven by `codex.event_map` in the DSL.
- opencode hook adapter with scaffold generator (`hook-loop opencode install`).
- `hook-loop codex install` scaffold generation with dry-run by default.
- See `gallery/` for 8 example DSLs and verify them all with `uv run python experiments/check_gallery_behavior.py`.

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

- A Codex hook adapter and generated scaffold are included (see above), driven by
  the `codex.event_map` in `hook-loop.json`. No Claude Code or pi adapter is
  included yet.
- Hook callbacks are in-process contracts, not a security boundary.
- `FakeAgent` and `FakeEvaluator` exist to make loop semantics deterministic in
  tests; the Codex adapter uses an event-sourced driver instead, because in Codex
  the agent is Codex itself rather than a fake.

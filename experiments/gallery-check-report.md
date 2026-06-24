# Experiment 2 Gallery Behavior Check

Outer opencode plan_execute: #14 fixed (plugin init no longer blocks). All 8 DSLs now have codex.event_map and produce Codex/opencode adapter traces.

Note: builder_evaluator and rework_loop stop at `evaluating` here because the
script has no external evaluator agent to emit a verdict prompt; simulate
reaches `done` via FakeEvaluator. In a real hook session, a prompt containing
'verdict: PASS' or 'NEEDS_WORK' would drive the evaluating state.

| DSL | validate | simulate | codex trace | opencode trace | issues |
| --- | --- | --- | --- | --- | ---: |
| agent_handoff | pass | done | terminal | terminal | 0 |
| approval_gate | pass | done | terminal | terminal | 0 |
| autoresearch_experiment | pass | done | terminal | terminal | 0 |
| builder_evaluator | pass | done | evaluating | evaluating | 2 |
| multi_agent_fanout | pass | done | working | working | 0 |
| plan_execute | pass | done | terminal | terminal | 0 |
| rework_loop | pass | done | evaluating | evaluating | 2 |
| safety_guardrail | pass | done | terminal | terminal | 0 |

## Details

### agent_handoff

Status: validate=pass, simulate=done.
Codex trace: `session_start --handoff_read--> read_handoff -> read_handoff --implemented--> implementing -> implementing --evidence_generated--> generate_evidence -> generate_evidence --committed--> commit_handoff -> commit_handoff --session_closed--> done`.
opencode trace: `session_start --handoff_read--> read_handoff -> read_handoff --implemented--> implementing -> implementing --evidence_generated--> generate_evidence -> generate_evidence --committed--> commit_handoff -> commit_handoff --session_closed--> done`.
Issues: none found by adapter-level comparison.

### approval_gate

Status: validate=pass, simulate=done.
Codex trace: `backlog --draft_ready--> drafting -> drafting --approval_requested--> pending_approval -> pending_approval --approval_granted--> approved -> approved --finalize--> done`.
opencode trace: `backlog --draft_ready--> drafting -> drafting --approval_requested--> pending_approval -> pending_approval --approval_granted--> approved -> approved --finalize--> done`.
Issues: none found by adapter-level comparison.

### autoresearch_experiment

Status: validate=pass, simulate=done.
Codex trace: `idle --experiment_init--> init_experiment -> init_experiment --experiment_run--> running -> running --experiment_log--> logging -> logging --metric_improved--> keep -> keep --commit--> done`.
opencode trace: `idle --experiment_init--> init_experiment -> init_experiment --experiment_run--> running -> running --experiment_log--> logging -> logging --metric_improved--> keep -> keep --commit--> done`.
Issues: none found by adapter-level comparison.

### builder_evaluator

Status: validate=pass, simulate=done.
Codex trace: `backlog --feature_selected--> building -> building --evidence_recorded--> evidence_ready -> evidence_ready --review_requested--> evaluating`.
opencode trace: `backlog --feature_selected--> building -> building --evidence_recorded--> evidence_ready -> evidence_ready --review_requested--> evaluating`.
Issues:
- codex: no simulation step for state `evaluating`
- opencode: no simulation step for state `evaluating`

### multi_agent_fanout

Status: validate=pass, simulate=done.
Codex trace: `backlog --kickoff--> dispatching -> dispatching --tasks_dispatched--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working`.
opencode trace: `backlog --kickoff--> dispatching -> dispatching --tasks_dispatched--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working -> working --worker_done--> working`.
Issues: none found by adapter-level comparison.

### plan_execute

Status: validate=pass, simulate=done.
Codex trace: `backlog --kickoff--> planning -> planning --plan_ready--> executing -> executing --step_done--> verifying -> verifying --all_steps_pass--> done`.
opencode trace: `backlog --kickoff--> planning -> planning --plan_ready--> executing -> executing --step_done--> verifying -> verifying --all_steps_pass--> done`.
Issues: none found by adapter-level comparison.

### rework_loop

Status: validate=pass, simulate=done.
Codex trace: `backlog --build_started--> building -> building --build_done--> evaluating`.
opencode trace: `backlog --build_started--> building -> building --build_done--> evaluating`.
Issues:
- codex: no simulation step for state `evaluating`
- opencode: no simulation step for state `evaluating`

### safety_guardrail

Status: validate=pass, simulate=done.
Codex trace: `idle --request_action--> action_requested -> action_requested --approve--> approved -> approved --action_executed--> executed -> executed --task_complete--> done`.
opencode trace: `idle --request_action--> action_requested -> action_requested --approve--> approved -> approved --action_executed--> executed -> executed --task_complete--> done`.
Issues: none found by adapter-level comparison.


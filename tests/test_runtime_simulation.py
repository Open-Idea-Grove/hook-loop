from hook_loop.evaluator import FakeEvaluator, Verdict
from hook_loop.events import new_event
from hook_loop.hooks import HookBus, HookContext, HookDecision
from hook_loop.runtime import AgentStep, FakeAgent, LoopRuntime, RuntimeBudget
from hook_loop.schema import LoopDefinition
from hook_loop.store import JsonlEventLog, recover_current_state


def delivery_definition():
    return LoopDefinition.from_dict(
        {
            "id": "software_delivery",
            "initial_state": "backlog",
            "states": ["backlog", "building", "evidence_ready", "evaluating", "needs_work", "done", "stopped"],
            "events": [
                "feature_selected",
                "evidence_recorded",
                "review_requested",
                "evaluator_passed",
                "evaluator_failed",
                "operator_stopped",
            ],
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
                {"from": "evaluating", "event": "evaluator_failed", "to": "needs_work"},
                {"from": "needs_work", "event": "feature_selected", "to": "building"},
            ],
        }
    )


def test_runtime_reaches_done_on_pass(tmp_path):
    runtime = LoopRuntime(
        definition=delivery_definition(),
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        agent=FakeAgent(
            {
                "backlog": [AgentStep("feature_selected")],
                "building": [AgentStep("evidence_recorded", {"evidence_id": "e1"})],
                "evidence_ready": [AgentStep("review_requested")],
            }
        ),
        evaluator=FakeEvaluator([Verdict("PASS", "evidence checked")]),
    )

    final_state = runtime.run_until_stop(RuntimeBudget(max_turns=5))

    assert final_state == "done"
    assert recover_current_state(runtime.store.read_all()) == "done"


def test_runtime_does_not_exhaust_budget_when_final_turn_reaches_done(tmp_path):
    runtime = LoopRuntime(
        definition=delivery_definition(),
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        agent=FakeAgent(
            {
                "backlog": [AgentStep("feature_selected")],
                "building": [AgentStep("evidence_recorded", {"evidence_id": "e1"})],
                "evidence_ready": [AgentStep("review_requested")],
            }
        ),
        evaluator=FakeEvaluator([Verdict("PASS", "evidence checked")]),
    )

    final_state = runtime.run_until_stop(RuntimeBudget(max_turns=3))

    assert final_state == "done"
    assert runtime.store.read_all()[-1].event_type == "state_transitioned"


def test_runtime_reworks_after_needs_work(tmp_path):
    runtime = LoopRuntime(
        definition=delivery_definition(),
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        agent=FakeAgent(
            {
                "backlog": [AgentStep("feature_selected")],
                "needs_work": [AgentStep("feature_selected")],
                "building": [
                    AgentStep("evidence_recorded", {"evidence_id": "first"}),
                    AgentStep("evidence_recorded", {"evidence_id": "second"}),
                ],
                "evidence_ready": [AgentStep("review_requested"), AgentStep("review_requested")],
            }
        ),
        evaluator=FakeEvaluator(
            [
                Verdict("NEEDS_WORK", "- missing screenshot"),
                Verdict("PASS", "fixed"),
            ]
        ),
    )

    final_state = runtime.run_until_stop(RuntimeBudget(max_turns=8))

    assert final_state == "done"
    event_types = [event.event_type for event in runtime.store.read_all()]
    assert event_types.count("verdict_recorded") == 2


def test_runtime_resumes_evaluating_state_without_agent_step(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    log.append(new_event("s1", "r1", "backlog", "session_initialized", "runtime", {"initial_state": "backlog"}))
    log.append(
        new_event(
            "s1",
            "r1",
            "evaluating",
            "state_transitioned",
            "runtime",
            {"from": "evidence_ready", "event": "review_requested", "to": "evaluating"},
        )
    )
    runtime = LoopRuntime(
        definition=delivery_definition(),
        store=log,
        agent=FakeAgent({}),
        evaluator=FakeEvaluator([Verdict("PASS", "resumed evaluation passed")]),
        session_id="s1",
    )

    final_state = runtime.run_until_stop(RuntimeBudget(max_turns=1))

    assert final_state == "done"
    assert runtime.store.read_all()[-1].event_type == "state_transitioned"


def test_runtime_recovers_only_matching_session(tmp_path):
    log = JsonlEventLog(tmp_path / "events.jsonl")
    log.append(new_event("other", "r1", "done", "state_transitioned", "runtime", {"to": "done"}))

    runtime = LoopRuntime(
        definition=delivery_definition(),
        store=log,
        agent=FakeAgent({"backlog": []}),
        evaluator=FakeEvaluator([]),
        session_id="s1",
    )

    final_state = runtime.run_until_stop(RuntimeBudget(max_turns=1, max_no_progress_turns=1))

    assert runtime.store.read_all()[1].session_id == "s1"
    assert runtime.store.read_all()[1].event_type == "session_initialized"
    assert final_state == "stopped"


def test_runtime_stops_on_no_progress_budget(tmp_path):
    runtime = LoopRuntime(
        definition=delivery_definition(),
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        agent=FakeAgent({"backlog": []}),
        evaluator=FakeEvaluator([]),
    )

    final_state = runtime.run_until_stop(RuntimeBudget(max_turns=2, max_no_progress_turns=1))

    assert final_state == "stopped"
    assert runtime.store.read_all()[-1].event_type == "budget_exhausted"


def test_runtime_blocks_transition_when_hook_blocks(tmp_path):
    hooks = HookBus()

    def require_evidence(context: HookContext) -> HookDecision:
        if context.event == "evaluator_passed":
            return HookDecision.block("missing bound evidence")
        return HookDecision.allow()

    hooks.register("before_state_transition", require_evidence)
    runtime = LoopRuntime(
        definition=delivery_definition(),
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        agent=FakeAgent(
            {
                "backlog": [AgentStep("feature_selected")],
                "building": [AgentStep("evidence_recorded", {"evidence_id": "e3"})],
                "evidence_ready": [AgentStep("review_requested")],
            }
        ),
        evaluator=FakeEvaluator([Verdict("PASS", "claimed pass")]),
        hooks=hooks,
    )

    final_state = runtime.run_until_stop(RuntimeBudget(max_turns=5))

    assert final_state == "stopped"
    assert runtime.store.read_all()[-1].event_type == "transition_blocked"


def test_runtime_preserves_transition_block_reason_when_no_progress_budget_is_one(tmp_path):
    hooks = HookBus()
    hooks.register("before_state_transition", lambda context: HookDecision.block("blocked"))
    runtime = LoopRuntime(
        definition=delivery_definition(),
        store=JsonlEventLog(tmp_path / "events.jsonl"),
        agent=FakeAgent({"backlog": [AgentStep("feature_selected")]}),
        evaluator=FakeEvaluator([]),
        hooks=hooks,
    )

    final_state = runtime.run_until_stop(RuntimeBudget(max_turns=1, max_no_progress_turns=1))

    assert final_state == "stopped"
    assert runtime.store.read_all()[-1].event_type == "transition_blocked"

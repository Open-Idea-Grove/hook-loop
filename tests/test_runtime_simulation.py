from hook_loop.evaluator import FakeEvaluator, Verdict
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

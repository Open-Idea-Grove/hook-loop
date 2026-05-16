from hook_loop.hooks import HookBus, HookContext, HookDecision


def test_hook_bus_allows_when_no_hooks_registered():
    bus = HookBus()
    decision = bus.fire("before_turn", HookContext(state="backlog", event=None, payload={}))

    assert decision.allowed is True
    assert decision.messages == []


def test_hook_bus_blocks_when_any_hook_blocks():
    bus = HookBus()
    bus.register("before_state_transition", lambda context: HookDecision.block("missing evidence"))

    decision = bus.fire(
        "before_state_transition",
        HookContext(state="evaluating", event="evaluator_passed", payload={}),
    )

    assert decision.allowed is False
    assert decision.messages == ["missing evidence"]


def test_hook_bus_collects_steer_messages():
    bus = HookBus()
    bus.register("before_turn", lambda context: HookDecision.allow("look at NEXT.md"))
    bus.register("before_turn", lambda context: HookDecision.allow("budget: 2 turns left"))

    decision = bus.fire("before_turn", HookContext(state="building", event=None, payload={}))

    assert decision.allowed is True
    assert decision.messages == ["look at NEXT.md", "budget: 2 turns left"]

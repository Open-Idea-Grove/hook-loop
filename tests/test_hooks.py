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


def test_hook_decision_exposes_verdicts_while_preserving_allowed_property():
    allow = HookDecision.allow("continue")
    block = HookDecision.block("missing evidence")
    steer = HookDecision.steer("look at NEXT.md")
    pause = HookDecision.pause("operator requested pause")
    replan = HookDecision.replan("fresh evaluator required")
    redact = HookDecision.redact("secret removed", patch={"content": "[REDACTED]"})

    assert allow.verdict == "allow"
    assert allow.allowed is True
    assert block.verdict == "block"
    assert block.allowed is False
    assert steer.verdict == "steer"
    assert steer.allowed is True
    assert pause.verdict == "pause"
    assert pause.allowed is False
    assert replan.verdict == "replan"
    assert replan.allowed is False
    assert redact.verdict == "redact"
    assert redact.allowed is True
    assert redact.patch == {"content": "[REDACTED]"}


def test_hook_context_carries_platform_normalized_fields():
    context = HookContext(
        state="building",
        event="action_requested",
        payload={"action": "test"},
        platform="codex",
        hook_event_name="PreToolUse",
        session_id="session-123",
        run_id="run-456",
        cwd="/repo",
        tool_name="Bash",
        tool_input={"command": "uv run pytest -q"},
        raw_input={"tool_name": "Bash"},
    )

    assert context.platform == "codex"
    assert context.hook_event_name == "PreToolUse"
    assert context.session_id == "session-123"
    assert context.run_id == "run-456"
    assert context.cwd == "/repo"
    assert context.tool_name == "Bash"
    assert context.tool_input == {"command": "uv run pytest -q"}
    assert context.raw_input == {"tool_name": "Bash"}

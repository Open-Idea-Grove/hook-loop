"""Platform-neutral hook loop runtime."""

from hook_loop.codex_adapter import CodexHookResult, handle_codex_hook, normalize_codex_hook_input
from hook_loop.codex_mapping import CodexEventMap, MatchSpec, RecordSpec, ResolvedRule
from hook_loop.codex_scaffold import CodexInstallResult, build_codex_scaffold, install_codex_scaffold
from hook_loop.opencode_scaffold import OpencodeInstallResult, build_opencode_scaffold, install_opencode_scaffold
from hook_loop.driver import ApplyResult, DefaultGuardEvaluator, EventSourcedLoopDriver, GuardEvaluator
from hook_loop.dsl import DslError, LoopSpec, SimulationSpec, load_loop_spec
from hook_loop.events import Event, new_event
from hook_loop.evaluator import FakeEvaluator, Verdict, parse_verdict
from hook_loop.hooks import HookBus, HookContext, HookDecision
from hook_loop.opencode_adapter import handle_opencode_hook, normalize_opencode_hook_input, normalize_opencode_tool_name
from hook_loop.runtime import AgentStep, FakeAgent, LoopRuntime, RuntimeBudget
from hook_loop.schema import LoopDefinition, SchemaError, Transition
from hook_loop.state_machine import StateMachine, TransitionRejected
from hook_loop.store import JsonlEventLog, recover_current_state

__version__ = "0.1.0"

__all__ = [
    "AgentStep",
    "ApplyResult",
    "CodexEventMap",
    "CodexHookResult",
    "CodexInstallResult",
    "DefaultGuardEvaluator",
    "DslError",
    "EventSourcedLoopDriver",
    "GuardEvaluator",
    "MatchSpec",
    "OpencodeInstallResult",
    "RecordSpec",
    "ResolvedRule",
    "Event",
    "FakeAgent",
    "FakeEvaluator",
    "HookBus",
    "HookContext",
    "HookDecision",
    "JsonlEventLog",
    "LoopDefinition",
    "LoopSpec",
    "LoopRuntime",
    "RuntimeBudget",
    "SchemaError",
    "SimulationSpec",
    "StateMachine",
    "Transition",
    "TransitionRejected",
    "Verdict",
    "new_event",
    "build_codex_scaffold",
    "handle_codex_hook",
    "handle_opencode_hook",
    "install_codex_scaffold",
    "load_loop_spec",
    "normalize_codex_hook_input",
    "normalize_opencode_hook_input",
    "normalize_opencode_tool_name",
    "parse_verdict",
    "recover_current_state",
]

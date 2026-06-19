# Loop Engineering 2026 patterns

Source: https://juejin.cn/post/7651450589566550026

Article: `Loop Engineering 深度实践指南：9 种 2026 年最新做法与完整代码`

Author: 米小虾

Published: 2026-06-16

Accessed: 2026-06-19

## 1. 文章概览

文章把 Loop Engineering 分成九类实践：轻量代码循环与图状态机、计划-执行双层循环、事件驱动和流式循环、多 agent 拓扑、长时持久化、自优化 loop、声明式配置、可观测断点与人工协同、安全护栏子循环。

对 `hook-loop` 最有价值的结论是：自主 agent 的工程关键不是单次 prompt，而是把循环拓扑、迁移条件、证据、审核、恢复和人工控制变成可执行 contract。当前仓库的状态机、hook bus、JSONL event log、evaluator verdict 和 JSON DSL 已经是这条路线的最小实现。

## 2. 和 hook-loop 的映射

| 文章 pattern | hook-loop 现状 | 可借鉴方向 |
| --- | --- | --- |
| 轻量图 + 代码节点 | `LoopDefinition`、`StateMachine`、`LoopRuntime` | 继续保持小核心，不急着引入 LangGraph；把 actions、resume policy、hook stages 做成 DSL 一等字段。 |
| 双层 loop | runtime 是外层 turn loop，agent adapter 是内层执行者 | 增加 plan artifact、step result、replan event，让复杂任务有战略/执行分层。 |
| 事件驱动 | `Event`、`JsonlEventLog` 已经 append-only | 将 hook fired、guard verdict、tool/action result 都统一成事件。 |
| 多 agent | 已有 builder/evaluator 分离基础 | 坚持 fresh evaluator；manager-worker 也应先落成状态机和事件日志。 |
| 耐久执行 | JSONL recovery 可恢复 current state | 补 idempotency key、snapshot、retry policy；Temporal 只作为 adapter 方向。 |
| 声明式配置 | `examples/software_delivery.json` 是最小 DSL | 扩展 guardrails、human-in-loop、observability、strategy metadata。 |
| 可观测断点 | HookBus 可 allow/block | 每次 hook decision 写入 event log，并扩展 steer/pause/replan 语义。 |
| 安全护栏 | transition guard + hook block | 增加 pre-action/post-action hook stage，覆盖危险操作、预算、敏感信息和审批。 |

## 3. 可借鉴的 pattern

### 3.1 轻量图 + 代码节点

文章比较了裸 while loop 和图状态机框架。`hook-loop` 更适合中间路线：

- 状态拓扑由 JSON DSL 定义，便于 diff、review、模拟和生成 adapter。
- 节点执行逻辑保留为普通 Python/平台 adapter 代码，便于断点调试。
- 状态机表达控制流，hook 做门禁、观测、预算和纠偏，不承载主业务。

对当前代码的直接影响：

- `Transition.actions` 可以从纯 schema 字段演进为受控 action dispatch。
- `Transition.resume_policy` 可以决定 turn 结束后是否 schedule resume。
- `HookContext` 应补 `session_id`、`run_id`、event id、transition/action reference。

### 3.2 Plan-execute 双层循环

复杂任务不要只依赖 agent 在一个平铺循环里局部决策。建议把 `LoopRuntime` 当外层 planner/state machine，把 agent adapter 当内层 executor。

建议新增事件：

- `plan_created`
- `plan_step_started`
- `plan_step_completed`
- `plan_step_failed`
- `replan_requested`
- `plan_revised`

这样 event log 不只记录“到了哪个状态”，还记录“为什么要继续、返工或重规划”。

### 3.3 Event log 作为 trace 底座

文章里的 observability、durable execution、self-optimization 都依赖结构化轨迹。当前 `JsonlEventLog` 是正确起点，下一步可补：

- hook decision 事件。
- guard missing / guard satisfied 事件。
- evaluator input digest 和 verdict digest。
- evidence id、artifact path、payload digest。
- cost、duration、attempt、retry_count。

这些字段同时支撑恢复、回放、调试、报表和未来策略优化。

### 3.4 安全护栏是子循环

安全不应只是 transition 上的一个 guard。更接近文章模式的结构是：

- pre-action：权限、预算、路径、审批、速率限制。
- post-action：secret/PII 扫描、输出大小、证据绑定、合规审计。
- verdict：allow、block、steer、pause、replan、redact。

## 4. 代码草图

下面的代码按当前 `hook_loop` 风格重写，用来说明可落地接口，不是文章代码的逐字搬运。

### 4.1 扩展 HookDecision

```python
from dataclasses import dataclass, field
from enum import StrEnum


class HookVerdict(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    STEER = "steer"
    PAUSE = "pause"
    REPLAN = "replan"
    REDACT = "redact"


@dataclass(frozen=True)
class HookDecision:
    verdict: HookVerdict
    messages: list[str] = field(default_factory=list)
    patch: dict | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict in {
            HookVerdict.ALLOW,
            HookVerdict.STEER,
            HookVerdict.REDACT,
        }
```

Runtime 映射：

- `BLOCK`：进入 stop/blocked state。
- `PAUSE`：写入 `operator_paused`，等待外部 resume。
- `REPLAN`：写入 `replan_requested`，将 reason 注入下一轮 agent contract。
- `STEER`：允许继续，同时记录 steering message。
- `REDACT`：允许继续，但 payload/output 应脱敏后落盘。

### 4.2 事件化 HookBus

```python
class EventedHookBus(HookBus):
    def __init__(self, store: JsonlEventLog, session_id: str, run_id: str):
        super().__init__()
        self.store = store
        self.session_id = session_id
        self.run_id = run_id

    def fire(self, stage: str, context: HookContext) -> HookDecision:
        decision = super().fire(stage, context)
        self.store.append(
            new_event(
                session_id=self.session_id,
                run_id=self.run_id,
                state=context.state,
                event_type="hook_fired",
                actor="hook",
                payload={
                    "stage": stage,
                    "event": context.event,
                    "allowed": decision.allowed,
                    "messages": decision.messages,
                },
            )
        )
        return decision
```

这个 pattern 能先用 JSONL 获得可观测性，不必立即接 LangSmith、Weave 或 Temporal。

### 4.3 Plan-execute artifact

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanStep:
    id: str
    description: str
    depends_on: tuple[str, ...] = ()
    status: str = "pending"
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    steps: tuple[PlanStep, ...]
    current_index: int = 0
    revision: int = 0
```

对应 DSL 草图：

```json
{
  "strategy": {
    "type": "plan_execute",
    "replan_on": ["evaluator_failed", "transition_rejected"],
    "step_events": ["plan_step_completed", "plan_step_failed"]
  }
}
```

### 4.4 pre-action 安全 hook

```python
def block_risky_action(context: HookContext) -> HookDecision:
    if context.event != "action_requested":
        return HookDecision.allow()

    action = context.payload.get("action", {})
    path = str(action.get("path", ""))
    command = str(action.get("command", ""))

    risky_path = any(part in path for part in (".git/", "/etc/", "production/"))
    risky_command = command.startswith(("rm ", "git reset", "drop "))

    if risky_path or risky_command:
        return HookDecision.block("risky action requires approval or replan")

    return HookDecision.allow()
```

建议新增 hook stages：

- `before_agent_turn`
- `before_action`
- `after_action`
- `before_state_transition`
- `after_state_transition`
- `before_resume`

### 4.5 snapshot 作为 JSONL 补充

JSONL 适合审计和 replay，但长任务反复扫描全量日志会变慢。可以追加快照事件，不破坏 append-only 原则：

```python
def append_snapshot(store: JsonlEventLog, runtime: LoopRuntime) -> None:
    store.append(
        new_event(
            session_id=runtime.session_id,
            run_id=runtime.run_id,
            state=runtime.current_state,
            event_type="state_snapshot",
            actor="runtime",
            payload={
                "current_state": runtime.current_state,
                "definition_id": runtime.definition.id,
                "terminal_states": list(runtime.definition.terminal_states),
            },
        )
    )
```

恢复策略：

1. 找最后一个 `state_snapshot`。
2. 从快照后 replay 后续状态、暂停、预算和 verdict 事件。
3. 快照 schema 不兼容时退回全量 replay。

## 5. DSL 扩展建议

当前 DSL 只有 `loop` 和 `simulation`。下一阶段可以扩展为：

```json
{
  "loop": {
    "id": "software_delivery",
    "initial_state": "backlog",
    "states": [],
    "events": [],
    "transitions": [],
    "budgets": {
      "max_turns": 20,
      "max_no_progress_turns": 2,
      "max_cost_usd": 5.0
    }
  },
  "strategy": {
    "type": "builder_evaluator",
    "planner": {"enabled": true},
    "replan_on": ["evaluator_failed", "transition_rejected"]
  },
  "guardrails": {
    "pre_action": ["block_risky_action", "require_approval_for_env"],
    "post_action": ["scan_secrets", "require_evidence_digest"]
  },
  "observability": {
    "record_hook_events": true,
    "record_cost": true,
    "record_duration": true
  },
  "human_in_the_loop": {
    "pause_events": ["operator_paused", "approval_required"]
  },
  "simulation": {}
}
```

## 6. 推荐优先级

### P0: 不引入重型运行时依赖

LangGraph、Temporal、LangSmith 都可以作为 adapter 或后端方向，但 `hook-loop` 的核心应继续保持标准库、小状态机、确定性 simulation。

### P1: hook decision 事件化

把每次 hook fire、verdict、message 写入 JSONL。这是可观测、审计、回放和安全分析的共同基础。

### P1: action-level hook stages

当前 runtime 只有 turn 和 transition 级别。安全护栏、人工审批、预算和输出审计需要 action 前后两个边界。

### P2: plan-execute artifact

引入 `ExecutionPlan`、`PlanStep` 和重规划事件，让复杂任务可恢复、可评价、可重放。

### P2: DSL 扩到 guardrails/observability/human-in-loop

先做 schema validation 和 simulation，不急着接真实平台 adapter。

### P3: async event bus 和 streaming

流式工具调用能降低延迟，但不是当前最关键风险。等 action/event schema 稳定后再做。

### P3: self-optimization

先积累高质量 event log。未来从成功/失败轨迹中提取 evaluator prompt、guard policy 和 strategy 配置的优化样本。

## 7. 获取与检索记录

- `opencli list -f yaml`：registry 中没有 `juejin` 站点适配器。
- `opencli juejin -h`：不可用，回退到通用读取。
- `opencli web read`：因 Browser Bridge 未连接失败。
- 网页工具打开文章 URL 只返回等待页。
- 最终方式：抓取掘金 SSR HTML，并从 `web_html_content` 提取文章正文用于分析。

# Hook Loop 自主 Agent 设计方法论与参考架构

日期：2026-05-16
状态：设计已确认，待实现规划

## 1. 背景与目标

本项目希望用 hook 实现外层 agent loop，并抽象出一套可复用的状态机设计
方法和自主 agent 设计原则。后续目标包括：

- 支持多种 agent loop 形态。
- 支持用户定义状态机，并生成对应的 hook loop agent。
- 在 Codex 中落地实现，同时保持平台中立的核心抽象。

当前仓库已有两份研究笔记：

- `docs/research/pi-autoresearch/readme.md`：实验优化型 loop，重点是 metric、
  keep/discard、checks、自动 commit/revert、turn-by-turn resume。
- `docs/research/cwc-long-running-agents/readme.md`：软件交付型 long-running
  harness，重点是 default-fail contract、fresh evaluator、handoff 和人工控制。

A 阶段产出一份方法论和参考架构文档，不实现 runtime、runner、hook 脚本或生成器。
B/C 阶段再分别落地可运行最小框架和用户状态机到 agent scaffold 的生成器。

## 2. 非目标

- 不绑定 Claude Code、Codex、pi 任一平台。
- 不实现具体 runner、generator 或平台 adapter。
- 不追求完整 agent 理论，只覆盖工程上可复用、可验证、可中断、可恢复的 loop 设计。
- 不把 hook 视为安全边界；安全隔离需要 sandbox、权限模型、只读 evaluator 和工作树隔离。

## 3. 阶段边界与验收标准

本 spec 同时描述 A/B/C 的连续路线，但后续实施必须分阶段规划，避免把方法论、runtime 和
generator 混成一个过大的任务。

### 3.1 A 阶段：设计文档

A 阶段已由本文覆盖。验收标准：

- 明确 hook loop agent 的核心术语和设计原则。
- 明确通用状态机模型、hook 分类和 contract 分类。
- 明确持久化、恢复、错误处理、预算和人工控制策略。
- 用实验优化型、软件交付型、通用任务型说明抽象如何落地。
- 提供非最终 DSL sketch，用于验证后续生成器方向。

### 3.2 B 阶段：最小可运行框架

B 阶段只实现 runtime，不实现用户生成器。验收标准：

- 能读取一个手写状态机 schema。
- 能执行 fake/headless agent turn，并记录 append-only event log。
- 能运行 hook bus、basic guards、fake evaluator。
- 能从 event log 恢复 state。
- 能通过 loop simulation tests 覆盖 pass、needs-work、no-progress、budget stop 和 operator stop。

### 3.3 C 阶段：用户状态机生成器

C 阶段在 B 阶段 runtime 稳定后开始。验收标准：

- 能从用户 DSL 生成 agent contract、hook payload schema、runner scaffold 和 simulation tests。
- 生成结果能通过 B 阶段 runtime 的模拟迁移测试。
- 生成器不绑定具体平台，Codex 只作为首个 adapter target。

## 4. 术语表

**Outer Loop**：包在 agent 外层的调度机制，负责决定继续、返工、停止或切换任务。

**Builder**：执行任务的主 agent。它可以产出工作、证据和完成声明，但不能独立完成最终验收。

**Evaluator**：独立验收 agent 或判定器。复杂任务必须使用 fresh context，避免 builder 自评。

**Hook**：在生命周期、工具调用、状态迁移或停止边界运行的 sidecar 逻辑。

**Contract**：agent、状态机、证据、handoff 和 hook 之间的结构化约定。

**Productive Event**：一次可证明的有效进展。外层 resume 必须绑定 productive event，避免 chat-only 自循环。

**Handoff**：跨 session 给人类和 fresh agent 读取的进度材料，通常是 Markdown。

**Event Log**：机器恢复的 append-only source of truth。

## 5. 设计原则

### 5.1 先设计状态机，再写 prompt

Prompt 只能指导 agent，不能可靠表达完成条件。每个 hook loop agent 都必须先定义状态、
事件、guard、action、持久化记录和 resume 策略，再把这些约束注入 agent contract。

### 5.2 自主执行，结构化约束

agent 可以自主选择策略，但关键迁移不能只依赖自然语言声明。完成、保留、回滚、
返工、停止必须绑定工具结果、event log、evidence、contract store 或 evaluator verdict。

### 5.3 Builder 不能独立验收自己

简单实验优化可以由 metric guard 和 correctness checks 处理。软件交付、主观质量或高风险
任务必须引入 fresh-context evaluator。builder 可以进入 `READY_FOR_REVIEW`，但不能单独进入
最终 `DONE`。

### 5.4 Conversation 是缓存，不是事实来源

恢复状态必须来自 event log、contract store、evidence ledger、handoff 文件和 git/checkpoint。
compaction summary 应由持久化状态确定性生成，不依赖 LLM 临时总结。

### 5.5 Hook 是 sidecar，不是主业务

hook 负责门禁、观测、注入、纠偏、预算和收尾。hook 不应承载主业务逻辑，也不应要求 agent
专门为 hook 填写字段。hook 可以读取 agent 自然产出的 description、verdict、evidence、
ASI/notes 等材料。

### 5.6 预算和停止条件是一等公民

自主 loop 必须有 max turns、max iterations、max failures、rate limit、人工 stop/pause 等
明确上限。`NEVER STOP` 只能作为 agent 行为提示，不能替代 runtime guard。

## 6. 通用状态机模型

通用 hook loop agent 可以抽象为：

```text
INACTIVE
→ INITIALIZED
→ READY
→ ACTING
→ OBSERVED
→ JUDGING
→ ACCEPTED | REJECTED | NEEDS_WORK | BLOCKED
→ RESUME | REWORK | STOPPED
```

每个迁移都必须声明：

```text
event: 发生了什么
guard: 什么条件允许迁移
action: 迁移时执行什么副作用
record: 写入什么持久化记录
resume_policy: 是否触发下一轮
```

### 6.1 实验优化型映射

```text
READY
→ RUNNING
→ AWAITING_LOG
→ LOGGED
→ KEEP | DISCARD | CRASH | CHECKS_FAILED
→ NEXT_RUN | STOPPED
```

关键语义：

- `run_experiment` 是 action boundary。
- `log_experiment` 是 observation 和 state transition boundary。
- `keep` 自动 checkpoint/commit。
- `discard`、`crash`、`checks_failed` 自动 rollback，但保留 loop state artifacts。
- 外层 resume 必须要求本 turn 至少发生一次实验记录。

### 6.2 软件交付型映射

```text
BACKLOG
→ BUILDING
→ EVIDENCE_READY
→ READY_FOR_REVIEW
→ EVALUATING
→ DONE | NEEDS_WORK
→ NEXT_ITEM | REWORK | STOPPED
```

关键语义：

- contract 中每个 criterion 默认 fail。
- builder 必须生成并读取 evidence 后才能声称 pass。
- evaluator 在 fresh context 中读取 spec、diff、evidence 后输出 `PASS` 或 `NEEDS_WORK`。
- `NEEDS_WORK` findings 进入下一轮 builder prompt 或 handoff。

### 6.3 通用任务型映射

通用任务型不预设 metric 或 feature。用户必须定义：

- 状态集合。
- productive event。
- 完成判定。
- 可恢复材料。
- 失败和返工路径。
- 预算和人工控制策略。

## 7. Hook 与 Contract 模型

### 7.1 Hook 分类

**Lifecycle Hook**

在 `before_agent_start`、`agent_end`、`on_compact`、`on_stop` 等边界运行。
用于注入 contract、安排 resume、生成 compaction summary、做 checkpoint。

**Gate Hook**

阻止不满足前置条件的迁移。例如没有 evidence 就不能把 criterion 标为 pass。

**Observation Hook**

记录 agent 已读证据、已产出日志、已完成 productive event。它提供事实，不直接判定完成。

**Steering Hook**

把外部纠偏注入下一轮，例如 `STEER.md` 或 before hook 的 stdout。

**Operator Control Hook**

提供 stop、pause、budget guard、rate-limit guard、熔断等人工或系统控制。

### 7.2 Contract 分类

**Agent Contract**

- 本轮开始必须读取哪些 source of truth。
- 本轮最多推进多少任务。
- 何时必须产出 observation、evidence 或 log。
- 哪些完成声明不能只靠自然语言。

**State Contract**

- 合法 states。
- 合法 events。
- state transition guards。
- accept、reject、rework、stop 的语义。

**Evidence Contract**

- 什么文件或结构化输出算证据。
- evidence 如何绑定 criterion。
- 谁可以把 criterion 标为 pass。

**Handoff Contract**

- 哪些状态必须持久化。
- session 重启如何恢复。
- compaction 后如何重建上下文。

**Hook Contract**

- hook 输入 schema。
- hook 输出语义。
- timeout、stdout、stderr 限制。
- hook 失败如何记录和处理。

## 8. 数据流、持久化与恢复

### 8.1 Event Log

event log 是机器恢复主线，推荐 append-only。事件类型包括：

```text
session_initialized
agent_turn_started
action_started
observation_recorded
evidence_registered
verdict_recorded
state_transitioned
hook_fired
resume_scheduled
budget_exhausted
operator_stopped
```

通用 event 必须包含：

- schema version。
- session id / run id。
- timestamp。
- current state。
- event type。
- actor。
- payload。
- payload digest 或证据引用。

### 8.2 Human Handoff

handoff 是给人类和 fresh agent 读的材料，不替代 event log。推荐结构：

```text
Goal
Current State
Done
In Progress
Next
Evidence
Open Questions
Notes
```

### 8.3 Evidence Store

evidence store 保存不能只靠口头描述的材料：

- screenshots。
- console logs。
- benchmark metrics。
- command output。
- diff。
- evaluator verdict。
- test results。

default-fail contract 的原则是：没有 evidence，不允许 pass。

### 8.4 恢复顺序

恢复时按以下顺序：

```text
从 event log 重建 state
→ 读取 contract store 和 evidence ledger
→ 读取 handoff markdown 辅助 agent 理解
→ 参考 git/checkpoint
→ 最后才参考 conversation summary
```

compaction summary 应从 event log、handoff、ideas/backlog、recent verdicts 确定性生成。

## 9. 错误处理、预算与人工控制

### 9.1 错误分类

**Task Failure**

任务没做好，但系统健康。进入 `discard`、`NEEDS_WORK` 或下一轮尝试。

**Action Failure**

命令崩溃、测试失败、工具异常。进入 `crash`、`checks_failed`、`BLOCKED` 或 `REWORK`。

**Loop Failure**

连续无进展、重复尝试、只聊天不产生 productive event、resume 自激活。需要
productive-event guard、anti-thrash、no-change limit。

**Runtime Failure**

hook 超时、event log 写入失败、compaction 丢状态、git 失败、API rate limit。
进入 `PAUSED` 或 `NEEDS_OPERATOR`，并记录可诊断错误。

### 9.2 预算

最小预算模型：

```text
max_turns
max_iterations
max_wall_time
max_cost
max_consecutive_failures
max_reworks_per_item
max_context_compactions
rate_limit_backoff
```

### 9.3 人工控制

最小人工控制：

```text
STOP: 阻止新动作或下一轮 resume
PAUSE: 暂停 loop，保留状态
STEER: 注入一次性纠偏
RESUME: 从持久化状态继续
ABORT_AND_ROLLBACK: 放弃当前尝试并恢复 checkpoint
FINALIZE: 从长期运行结果整理成可 review 的产物
```

每个 stop path 都必须说明：

- 是否允许恢复。
- 是否需要 rollback。
- 是否写入 final event。
- 是否更新 handoff。
- 是否通知 human。

## 10. 参考架构

后续 B/C 阶段可以落成以下模块：

```text
Loop Runtime
  - 加载状态机定义
  - 调度 agent turn
  - 执行状态迁移
  - 管理 resume/rework/stop

State Store
  - append-only event log
  - contract store
  - evidence ledger
  - handoff writer

Hook Bus
  - lifecycle hooks
  - gate hooks
  - observation hooks
  - operator-control hooks

Action Runtime
  - command/tool execution
  - structured output parsing
  - checkpoint/rollback
  - evidence capture

Evaluator Layer
  - simple guard evaluator
  - fresh-context evaluator adapter
  - verdict parser

Platform Adapter
  - Codex adapter
  - Claude Code adapter
  - pi adapter
  - headless wrapper adapter

Generator
  - DSL/schema parser
  - state machine validator
  - hook contract generator
  - runner scaffold generator
```

平台中立层只定义状态机、contract、event log、hook 语义。平台 adapter 负责把这些语义映射到
Codex、Claude Code、pi 或 Agent SDK 的具体事件和工具系统。

## 11. 测试与验证策略

### 11.1 State Machine Contract Tests

验证每个状态只接受合法事件，guard 生效，非法迁移被拒绝。例如 `READY` 不能直接进入
`DONE`，`NEEDS_WORK` 必须带 evaluator finding 才能进入 `REWORK`。

### 11.2 Hook Contract Tests

用 mock payload 测试 hook stdin schema、stdout 截断、stderr 处理、timeout、非零退出、
observability event。hook 失败不能无声吞掉，也不能破坏可恢复状态。

### 11.3 Persistence / Recovery Tests

从 event log 重建 state。覆盖 hook event 不污染业务事件、schema version 升级、compaction
summary 确定性生成、中途崩溃、重复事件、部分写入、handoff 缺失、evidence 缺失。

### 11.4 Loop Simulation Tests

用 fake agent 和 fake evaluator 跑完整 loop，不调用真实 LLM。覆盖 `PASS`、`NEEDS_WORK`、
连续失败、无 productive event、预算耗尽、operator stop、resume after compaction。

### 11.5 End-to-End Smoke Tests

B/C 阶段再加少量真实平台适配测试，例如 Codex adapter 能启动 loop、写 event log、触发
evaluator、恢复状态。E2E 只测关键路径，不把 LLM 行为作为唯一断言。

### 11.6 Generator Tests

生成器方向必须验证：

```text
用户 DSL → 状态机定义
状态机定义 → hook contract
hook contract → runner scaffold
runner scaffold → simulation pass
```

核心断言不是“生成了文件”，而是“生成出的 loop 能通过模拟状态迁移和恢复测试”。

## 12. 风险与反模式

- 只靠 prompt 写 `NEVER STOP`，没有预算、终止策略和外部开关。
- 外层 resume 只靠“发送用户消息”驱动，缺少 checkpoint/job queue 抽象。
- `git add -A` 和全工作区 revert 太粗，应优先 worktree/sandbox 或显式 changeset。
- hook stderr 不限大小，hook log 不保存诊断上下文，导致审计和 debug 困难。
- domain 概念硬编码为 metric/keep/discard，通用版应抽象成 observation、verdict、
  acceptance action、rollback action。
- 文档与实现分叉。例如研究项目中 compaction 后是否重读文件的说明和实现存在轻微不一致。
- Markdown 适合人类阅读，但机器恢复必须有 schema/version。
- hook 多数不是安全边界。Write/Edit gate 可被 shell 写文件绕过，steer 文件也可能被有写
  权限的 agent 修改。
- kill switch 通常只能阻止后续 tool call，不能杀掉已经启动的外部进程。

## 13. 附录：非最终 DSL Sketch

此 DSL 只用于验证抽象能否支持“用户定义状态机 → 生成 hook loop agent”。它不是最终格式承诺。

```yaml
agent_loop:
  id: software_delivery
  objective: Deliver features with evidence-backed review

  budgets:
    max_turns: 20
    max_reworks_per_item: 3
    max_consecutive_no_progress: 2

  states:
    - id: todo
    - id: building
    - id: evidence_ready
    - id: evaluating
    - id: needs_work
    - id: done
    - id: stopped

  events:
    - id: feature_selected
    - id: evidence_recorded
    - id: review_requested
    - id: evaluator_passed
    - id: evaluator_failed
    - id: operator_stopped

  transitions:
    - from: todo
      event: feature_selected
      to: building
      actions: [load_handoff, inject_agent_contract]

    - from: evidence_ready
      event: review_requested
      to: evaluating
      actions: [invoke_fresh_evaluator]

    - from: evaluating
      event: evaluator_failed
      to: needs_work
      actions: [write_findings, update_handoff]
      resume_policy: rework

    - from: evaluating
      event: evaluator_passed
      to: done
      guards: [evidence_bound_to_criteria]
      actions: [mark_contract_passed, checkpoint]

  hooks:
    before_turn:
      input: [state, handoff, budget]
      output: steer_message
    before_state_transition:
      input: [from, event, to, evidence]
      output: allow_or_block
    on_stop:
      actions: [checkpoint, write_final_event]

  contracts:
    productive_event: evidence_recorded
    completion_requires: [fresh_evaluator_pass, evidence_bound_to_criteria]
    handoff: PROGRESS.md
    event_log: hook-loop.jsonl
```

## 14. B/C 阶段建议

B 阶段先实现最小可运行框架：

- 读取一个状态机 schema。
- 运行 fake 或 headless agent turn。
- 写 append-only event log。
- 支持 hook bus 和 basic guards。
- 支持 fake evaluator。
- 跑 loop simulation tests。

C 阶段再实现生成器：

- 从用户状态机 DSL 生成 agent contract。
- 生成 hook payload schema。
- 生成 runner scaffold。
- 生成 simulation tests。
- 生成 Codex adapter skeleton。

# DEVELOPMENT.md — hook-loop 项目开发经验与接力指引

> 本文档总结 hook-loop 项目从立项到 Codex/opencode 适配的完整开发历程、关键设计决策、踩坑经验和后续接力方向，供新同事快速上手。

## 1. 项目概述

**hook-loop** 是一个平台中立的自主 agent 外层 loop 实验项目。核心思想：把 agent 的循环拓扑、迁移条件、证据、审核、恢复和人工控制变成**可执行 contract**（JSON DSL），而不是埋在单次 prompt 里。

**设计依据**：`docs/research/loop-engineering-2026-patterns/readme.md`（掘金《Loop Engineering 9 种 2026 做法》研究笔记）。该文档把 9 种 loop pattern 映射到 hook-loop 的现状和后续方向，是理解项目设计意图的最佳入口。

**技术栈**：Python 3.11+，标准库为主，pytest via `uv`，`src/` layout。刻意不引入 LangGraph/Temporal/LangSmith 等重运行时（research doc P0 原则）。

## 2. 项目演进时间线

项目分三个阶段，25 个 commit：

### 阶段 A：B-stage 运行时（`docs/superpowers/plans/2026-05-16-hook-loop-runtime-plan.md`）

**目标**：最小状态机 + 事件日志 + hook bus + 仿真，无平台 adapter。

- `schema.py` / `state_machine.py` — 状态机契约（states/events/transitions/guards）。
- `events.py` / `store.py` — append-only JSONL 事件日志 + 状态恢复。
- `hooks.py` — 进程内 hook bus（allow/block/steer）。
- `evaluator.py` — verdict 解析 + FakeEvaluator。
- `runtime.py` — `LoopRuntime` + `FakeAgent`，预算驱动的 turn 循环仿真。
- 7 个 commit，纯 TDD，每个模块先写失败测试再实现。

**关键设计**：runtime 是**仿真模型**——`FakeAgent` 按 `agent_steps[state]` 顺序吐 step，`FakeEvaluator` 按 `verdicts` 顺序吐 verdict，`TransitionRejected` 时直接跳 `stop_state` 杀会话。这适合离线测试，不适合真实 agent。

### 阶段 B：C-stage DSL + CLI（`docs/superpowers/plans/2026-05-16-hook-loop-dsl-cli-plan.md`）

**目标**：JSON DSL 加载 + validate/simulate CLI。

- `dsl.py` — `load_loop_spec` 把 `hook-loop.json` 解析成 `LoopSpec(definition, simulation)`。
- `cli.py` — `hook-loop validate` / `hook-loop simulate`。
- `examples/software_delivery.json` — canonical DSL 示例。
- schema 加 `terminal_states` / `stop_state`，runtime 用 schema 定义而非硬编码。

### 阶段 C：Codex hook adapter + 状态机驱动（`ce1a53e` → `d057982`）

这是本次开发的重点。分两轮：

#### 第一轮（`ce1a53e`）：MVP adapter + scaffold

`ce1a53e` 加了 Codex hook adapter，但 review 发现它**没有真正驱动状态机**：
- `handle_codex_hook` 走硬编码分支（按 Codex 事件名 if/else），不碰 `LoopRuntime`/`StateMachine`。
- `hook-loop.json` 只过 schema 校验，结果被丢弃（`cli.py` 的 `load_loop_spec` 返回值没赋给任何变量）。
- 脚手架生成的 `.codex/hooks/hook_loop_codex.py` 是死代码（只有 `raise SystemExit(0)`，hooks.json 不调它）。

**这是设计上的已知边界**，不是 bug——plan 文档明确把"真实 Codex adapter"划在范围外。但 MVP 容易让人误以为"三件套=状态机实现"。

#### 第二轮（`d057982`）：真正驱动状态机

为解决上述问题，实施了 6 个 chunk 的 TDD 改造：

| Chunk | 内容 | 关键文件 |
|---|---|---|
| 0 | 修正 README 过期边界说明 | `README.md` |
| 1 | 新增 `EventSourcedLoopDriver`（与 `LoopRuntime` 并列，不依赖 FakeAgent） | `driver.py`, `test_driver.py` |
| 2 | 新增 `codex.event_map` DSL 解析（声明式事件映射） | `codex_mapping.py`, `dsl.py`, `test_codex_mapping.py` |
| 3 | 重写 `handle_codex_hook` 接 driver + mapping | `codex_adapter.py`, `test_codex_adapter.py` |
| 4 | 脚手架移除死代码、生成 `codex` 段 | `codex_scaffold.py`, `test_codex_scaffold.py` |
| 5 | 全量验证 + 回填 README | `README.md` |

随后加 `--dsl` 支持，让 `codex install` 能嵌入任意用户 DSL（`install_codex_scaffold(dsl_path=...)`）。

## 3. 核心架构（当前状态）

```
hook-loop.json
  └─ loop ──→ LoopDefinition ──→ StateMachine
  └─ codex.event_map ──→ CodexEventMap.resolve(ctx) ──→ (record + emit)
  └─ simulation ──→ FakeAgent/FakeEvaluator ──→ LoopRuntime.run_until_stop (离线仿真)

两个执行入口：
  1. hook-loop simulate (离线): LoopRuntime + FakeAgent + FakeEvaluator
  2. hook-loop codex-hook (在线): handle_codex_hook → EventSourcedLoopDriver + CodexEventMap
```

### 关键模块职责

| 模块 | 职责 | 何时用 |
|---|---|---|
| `schema.py` | `LoopDefinition` 数据类 + 校验 | 所有路径共用 |
| `state_machine.py` | `StateMachine.apply(state, event, guards)` | 所有路径共用 |
| `runtime.py` | `LoopRuntime` + `FakeAgent`（仿真预算模型） | 仅 `simulate` 命令 |
| `driver.py` | `EventSourcedLoopDriver`（事件溯源，单步驱动） | Codex/opencode hook |
| `codex_mapping.py` | `MatchSpec`/`CodexEventMap`（声明式事件映射） | hook 路径 |
| `codex_adapter.py` | `handle_codex_hook`（接 driver + mapping + 护栏） | `codex-hook` CLI |
| `codex_scaffold.py` | 生成 `.codex/hooks.json` + `hook-loop.json` | `codex install` CLI |
| `dsl.py` | `load_loop_spec`（加载 + 校验 DSL） | 所有 CLI 命令 |

### `LoopRuntime` vs `EventSourcedLoopDriver` 的关键差异

这是最容易混淆的设计点：

| | `LoopRuntime` | `EventSourcedLoopDriver` |
|---|---|---|
| 用途 | 离线仿真 | 真实 Codex/opencode hook |
| agent | `FakeAgent`（按序吐 step） | 无（agent 是 Codex 本身） |
| evaluator | `FakeEvaluator`（按序吐 verdict） | 无（verdict 从 prompt 解析） |
| TransitionRejected | 跳 `stop_state` 杀会话 | 只记录 `transition_rejected`，不迁移 |
| 驱动方式 | `run_until_stop(budget)` 自动循环 | `apply_event(event)` 单步，外部调 |

**为什么 driver 不像 runtime 那样跳 stop_state**：真实会话里一次不匹配的 emit 不应杀掉整个 session（agent 可能在 backlog 阶段误触发 evidence_recorded，不应直接 stopped）。

## 4. DSL 写法速查

```json
{
  "loop": {                          // 状态机契约（必需）
    "id", "initial_state", "states", "terminal_states", "stop_state",
    "events", "transitions": [{from, event, to, guards}]
  },
  "simulation": {                    // 离线仿真夹具（仅 simulate 命令用）
    "budget": {"max_turns", "max_no_progress_turns"},
    "agent_steps": {"state": [{"event", "payload"}]},
    "verdicts": [{"status": "PASS|NEEDS_WORK", "details"}]
  },
  "codex": {                         // Codex hook 行为映射（仅 codex-hook 用）
    "event_map": [
      {
        "codex_event": "PostToolUse|UserPromptSubmit|...",
        "when": {"tool_name", "command_match", "prompt_match", "exit_code"},
        "record": {"event_type", "actor", "payload", "include"},
        "emit": "loop_event_name",
        "guard_satisfied": ["guard_name"]
      }
    ]
  }
}
```

- `when` 条件全 AND，空 `when` 恒匹配，regex 用 `re.search`。
- 多条规则可匹配同一 Codex 事件，按序执行。
- `emit` 必须 ∈ `loop.events` 且至少一条 transition 用到它。
- `record` 在 emit 前先 append side-effect 事件（如 `evidence_registered`）。
- `guard_satisfied` 显式声明本规则满足的 guard（因为内置 evaluator 只有 `evidence_bound_to_criteria`）。

## 5. 开发经验与踩坑

### 5.1 TDD 是这个项目的基石

每个模块都先写失败测试再实现。`docs/superpowers/plans/` 下的两份 plan 文档是 TDD 脚本，每步含"写失败测试→跑→实现→跑→commit"。**接力开发时务必保持这个节奏**——状态机逻辑极易出错，没有测试覆盖不敢动。

### 5.2 `recover_current_state` 的 else 分支会吃掉状态

**踩坑**：`store.py:recover_current_state` 的 else 分支用 `event.state` 覆盖 current。如果观测事件（`hook_fired`/`evidence_registered`）的 `state` 字段填了 `"unknown"`（来自 hook 输入），会污染状态恢复。

**解法**：`handle_codex_hook` 里所有 record 事件的 `state` 字段用 `driver.current_state`（真实状态），不用 `context.state`（hook 输入的原始 state，常为 "unknown"）。见 `codex_adapter._record_hook_event` 的 `state` 参数。

### 5.3 `codex.event_map` 的 `exit_code` 字段路径

`MatchSpec.exit_code` 检查 `context.payload["tool_output"]["exit_code"]`。但 codex PostToolUse 的真实 payload 字段路径可能不同——这是 ISSUE.md #4 的根因。**接力时第一件事**：dump 一次真实 codex PostToolUse stdin payload，确认字段结构，必要时加容错。

### 5.4 项目级 hook 必须 CODEX_HOME

codex 0.142.0 **只从 `CODEX_HOME` 读 `hooks.json`**，不读项目级 `.codex/hooks.json`。实测确认：
- `.codex/hooks.json` 不设 CODEX_HOME → 0 events。
- `CODEX_HOME=.codex-home` → 7+ events。

详见 `AGENTS.md` 的项目级设置步骤。

### 5.5 hook 命令必须用绝对路径

codex hook 在子进程执行，`hook-loop` 不在 PATH（它在 `.venv/bin/`）。scaffold 生成的 `hook-loop codex-hook ...` 会静默失败。必须改写为 `/abs/path/.venv/bin/hook-loop codex-hook ...`。见 `AGENTS.md` 步骤 3。

### 5.6 `codex exec` 无视 Stop hook block

`codex exec` 是无头模式，Stop hook 返回 exit code 2 时 agent 不会继续——它直接结束 turn。Stop gate 在 exec 模式下退化为事后审计。交互模式可能不同，但未测。这是 ISSUE.md #1。

### 5.7 `simulation` 段对真实运行无作用

`simulation` 只被 `hook-loop simulate` 用。真实 Codex/opencode hook 路径只用 `loop` + `codex.event_map`。脚手架把 `simulation` 一起写进 `hook-loop.json` 容易让人误解它影响真实行为。考虑后续拆分文件。

### 5.8 opencode 事件契约与 Codex 完全不同

opencode 是 JS/TS 插件模型，事件名是 `tool.execute.before/after`、`session.idle`、`message.updated`，工具名小写（`bash`/`edit`/`write`），阻断方式是 `throw new Error()`。与 Codex 的 `PreToolUse/PostToolUse/Stop` + 大写工具名 + exit code 2 完全不同。需要翻译层（`opencode_adapter.py`）。

## 6. 当前实测状态

### 已验证可用

- `hook-loop validate` / `simulate` / `codex-hook` / `codex install --dsl` CLI 全部可用。
- `EventSourcedLoopDriver` + `codex.event_map` 能驱动 software_delivery 和 plan_execute 两个 DSL。
- 项目级 `CODEX_HOME` + `.codex-home/hooks.json` 让 hooks 在不动全局的前提下生效。
- `opencode mcp list` 显示 `✓ codex connected`，codex MCP 暴露 `codex_codex` / `codex_codex-reply` 工具。
- 真实 `codex exec` 运行时 hooks fire（75 events），状态机推进了 `backlog→planning`，Stop gate 正确 block。
- codex agent 独立完成了 opencode adapter 实施（94 passed，+5 新测试）。

### 未解决（见 ISSUE.md）

- **P0**：codex exec 无视 Stop block；项目级 `.codex/hooks.json` 不被读（已用 CODEX_HOME 绕过）。
- **P1**：hook-loop 不在 PATH（已用绝对路径绕过）；PostToolUse `step_done` 对真实命令不触发；`plan_ready` 需要 agent 发特定文本；loop 无法阻止 agent 在非 terminal 状态下干活。
- **P2**：bwrap sandbox 在 worktree 环境损坏；PreToolUse 护栏对 apply_patch 误拦。

## 7. 接力开发指引

### 7.1 上手顺序

1. 读 `docs/research/loop-engineering-2026-patterns/readme.md` 理解设计意图。
2. 读本文件第 3 节理解架构，第 4 节理解 DSL 写法。
3. 跑 `uv sync && uv run pytest -q`（当前 94 passed）。
4. 跑 `uv run hook-loop validate examples/software_delivery.json` 和 `simulate`。
5. 读 `AGENTS.md` 搭建项目级 CODEX_HOME 验证环境。
6. 读 `ISSUE.md` 了解未解决问题，按优先级接手。

### 7.2 优先修复方向

1. **ISSUE #1 + #4**：让 Stop gate 在 codex exec 下真正生效（外层循环 resume），并修 PostToolUse `step_done` 的 exit_code 字段路径——修后 plan_execute loop 能真正推进到 done。
2. **ISSUE #5**：`plan_ready` 触发方式从 `UserPromptSubmit` 改为 `PostToolUse` + 文件路径匹配，或 planning 状态下首次工具调用自动转 executing。
3. **ISSUE #6**：PreToolUse 护栏加状态感知（planning 状态禁写、executing 禁测试、verifying 只跑测试），让 loop 从事后审计升级为事前 gating。
4. **opencode 完整支持**：把 `opencode_adapter.py` 从实验代码升级为正式模块（加测试、导出、scaffold 生成 `.opencode/plugins/hook_loop.js`）。

### 7.3 开发约定

- **TDD**：先写失败测试，跑，实现，跑，commit。
- **不碰全局**：所有 codex 配置走项目级 `CODEX_HOME`，不写 `~/.codex/`。
- **绝对路径**：scaffold 生成的 hook 命令必须用绝对路径调 `hook-loop`。
- **不引入重依赖**：核心保持标准库 + pytest，LangGraph/Temporal 只作为 adapter 方向。
- **commit 风格**：`feat:` / `fix:` / `docs:` / `test:` / `chore:`，参考 `git log --oneline`。
- **不主动 commit/push**：除非用户明确要求。

### 7.4 关键文件索引

| 文件 | 作用 |
|---|---|
| `README.md` | 用户文档 + 验证步骤 |
| `AGENTS.md` | 项目级 CODEX_HOME 设置指引 |
| `ISSUE.md` | 未解决问题清单（含复现命令） |
| `examples/software_delivery.json` | canonical DSL 示例 |
| `examples/plan_execute.json` | Plan-Execute 双层 DSL 示例 |
| `experiments/probe_opencode_mismatches.py` | opencode 失败模式探针 |
| `experiments/drive_plan_execute_with_opencode.py` | 端到端驱动实验 |
| `docs/research/loop-engineering-2026-patterns/readme.md` | 设计依据 + 后续 P0-P3 路线图 |
| `docs/superpowers/specs/2026-05-16-hook-loop-agent-design.md` | 原始设计 spec |
| `docs/superpowers/plans/2026-05-16-hook-loop-runtime-plan.md` | B-stage TDD 实施脚本 |
| `docs/superpowers/plans/2026-05-16-hook-loop-dsl-cli-plan.md` | C-stage TDD 实施脚本 |

### 7.5 验证清单（接力时先跑这些）

```bash
uv sync && uv run pytest -q                                    # 94 passed
uv run hook-loop validate examples/software_delivery.json      # valid: software_delivery
uv run hook-loop simulate examples/software_delivery.json --event-log /tmp/e.jsonl  # final_state: done
uv run hook-loop codex install --profile plan_execute --dsl examples/plan_execute.json --target directory --destination /tmp/preview --write  # 生成两件套
opencode mcp list                                              # ✓ codex connected
CODEX_HOME=$PWD/.codex-home codex exec ...                     # .hook-loop/events.jsonl 有 hook_fired
```

# ISSUE.md — hook-loop × Codex / opencode 实测问题清单

> 生成时间：2026-06-23（持续更新）
> 实验一：用 Plan-Execute DSL 生成 Codex 脚手架，启动 `codex exec` agent 实施 opencode adapter 支持。证据存于 `.hook-loop/events.jsonl`（75 events）和 `/tmp/codex-opencode-run.jsonl`（97 events）。
> 实验二：用 Plan-Execute DSL 生成 opencode 脚手架（手动建插件），启动 `opencode run` agent 实施 gallery 功能。证据存于 `.hook-loop/events.jsonl`（144 events）。
> 实验二追加验证：用双层 `plan_execute` 尝试让 opencode agent 检查 `gallery/` 里 8 个 DSL 的 Codex/opencode 行为一致性；opencode run 在 hook 初始化后 timeout，随后用 adapter-level 驱动补全矩阵。报告：`experiments/gallery-check-report.md`。
> 实验二重做：#14 修复后重跑双层 plan_execute；hooks 正常 fire（64 events）但 loop 仍卡在 planning（#18: message.updated 从未 fire）。

## 实验结论（先读这段）

### 实验一：Codex agent

**Codex agent 独立完成了功能实施**：创建了 `src/hook_loop/opencode_adapter.py`（168 行）+ `tests/test_opencode_adapter.py`（218 行）+ 修改 `cli.py` 加 `opencode-hook` 子命令，`uv run pytest -q` **94 passed**（基线 89 + 5 新测试）。agent 的实现方案（事件名翻译表 + 工具名归一化 + 复用 `handle_codex_hook`）与设计预期一致。

**但 plan-execute loop 只推进了 1 步就卡住**：状态机从 `backlog→planning`（kickoff）后再无转移。agent 在 `planning` 状态下直接完成了所有工作并停止，Stop gate 发出了 `replan` 但被 codex exec 无视。以下是 8 个实测发现的问题。

---

## Issue #1 [P0/阻塞] `codex exec` 无视 Stop hook 的 exit code 2，agent 直接停止

**现象**：agent 完成工作后触发 `Stop` 事件。`handle_codex_hook` 正确判定 state=planning（非 terminal），返回 `exit_code=2` + `"Cannot stop yet. Required next steps: record evidence; run and record verification; obtain fresh evaluator PASS. Next events from planning: plan_ready"`。但 `codex exec` 没有把这个 replan 消息喂回 agent 并强制继续，而是直接结束 turn（`turn.completed`）。

**证据**：
```
.hook-loop/events.jsonl 最后一行:
  stop_contract_failed  state=planning  msg=Cannot stop yet. Required next steps: ...
/tmp/codex-opencode-run.jsonl:
  最后一组事件: item.completed(agent_message) → turn.completed  (agent 正常结束)
```

**根因**：`codex exec` 是无头模式，没有"Stop hook block 后继续对话"的机制。Stop hook 的 exit code 2 在交互模式下可能有效（阻止 agent 停止并提示），但在 exec 模式下只是记录，不影响 turn 结束。

**建议修复**：
1. 短期：在 `codex exec` 下检测 Stop hook 返回 exit_code=2 时，外层脚本自动用 replan 消息发起一轮新的 `codex exec resume`，形成外层循环。
2. 长期：研究 codex 是否有 `--on-stop-block` 选项或 API 来处理 Stop hook 反馈；或改用 `codex` 交互模式 + 远程控制 API。

**严重度**：P0（Stop gate 是 loop 的核心质量门，exec 模式下完全失效）。

---

## Issue #2 [P0/阻塞] 项目级 `.codex/hooks.json` 不被 codex 0.142.0 读取

**现象**：`codex install` 生成的 `.codex/hooks.json` 放在项目根目录，但 codex exec 运行时 hooks 完全没 fire（`.hook-loop/events.jsonl` 未创建）。把同一份 `hooks.json` 复制到 `~/.codex/hooks.json`（全局）后，hooks 立即正常 fire。

**证据**：
```bash
# 项目级（不工作）:
ls .codex/hooks.json   # 存在
codex exec ...          # .hook-loop/events.jsonl 未创建

# 全局级（工作）:
cp .codex/hooks.json ~/.codex/hooks.json
codex exec ...          # .hook-loop/events.jsonl 有 9~75 个事件
```

**根因**：codex 0.142.0 的 hooks 发现机制只读 `~/.codex/hooks.json`，不读项目级 `.codex/hooks.json`。`codex_scaffold.py` 生成的是项目级路径，与 codex 实际发现机制不匹配。figma 插件的 hooks.json 也是通过 plugin 系统在 `~/.codex/` 下加载的。

**建议修复**：
1. `codex_scaffold` 的 `--target` 区分 `project`（生成到 `~/.codex/hooks.json`）和 `user`（同上），不再生成项目级 `.codex/hooks.json`。
2. 或生成一个 install 脚本，把 `.codex/hooks.json` symlink/copy 到 `~/.codex/`。
3. 确认 codex 文档中 hooks 发现路径的官方说明。

**严重度**：P0（按当前 scaffold 指引安装的 hooks 根本不生效）。

---

## Issue #3 [P1/高] `hook-loop` 不在 codex hook 执行环境的 PATH 中

**现象**：scaffold 生成的 hooks.json 命令是 `hook-loop codex-hook --event Stop ...`。codex hook 在 sandbox/子进程中执行时，`hook-loop` 不在 PATH（它只存在于项目 `.venv/bin/`），hook 命令静默失败。改用绝对路径 `/home/.../.venv/bin/hook-loop` 后才工作。

**证据**：
```bash
# 原始 hooks.json (不工作):
"command": "hook-loop codex-hook --event Stop ..."
# 修改后 (工作):
"command": "/home/blizhan/.paseo/worktrees/0qsy20m0/mad-zebra/.venv/bin/hook-loop codex-hook --event Stop ..."
```

**根因**：`codex_scaffold._hook_group` 硬编码 `hook-loop` 作为命令前缀，假设它在 PATH 上。但 `uv` 管理的 venv 不会全局暴露 entrypoint。

**建议修复**：
1. scaffold 生成时探测 `hook-loop` 的绝对路径（`shutil.which("hook-loop")` 或 `sys.executable` 旁的 `hook-loop`），写入 hooks.json。
2. 或生成一个 wrapper 脚本（如 `.codex/hook-loop-wrapper.sh`）设置 PATH 后调用 `hook-loop`。
3. 或文档要求用户 `uv tool install hook-loop` 全局安装后再 `codex install`。

**严重度**：P1（hooks 静默失败，用户无感知 loop 没在运行）。

---

## Issue #4 [P1/高] PostToolUse 的 `step_done` 规则对真实 codex 命令不触发

**现象**：agent 运行了 `rtk uv run pytest -q`（exit_code=0，输出 "94 passed"），触发了 35 次 PostToolUse hook，但 `step_done` 转移从未发生。状态机始终停在 `planning`，未进入 `executing`→`verifying`。

**证据**：
```
.hook-loop/events.jsonl:
  PostToolUse hook_fired: 35 次, 全部 verdict=allow, 无 state_transitioned
  state_transitioned: 仅 1 次 (kickoff)
```

**根因**（需进一步确认）：`step_done` 规则的 `when` 条件是 `{"tool_name": "Bash", "command_match": "pytest|test|...", "exit_code": 0}`。虽然 `tool_name` 是 "Bash" 且命令含 "pytest"，但 `exit_code` 条件可能不匹配——codex PostToolUse payload 中 `tool_output.exit_code` 的字段路径可能与 `MatchSpec` 预期的 `context.payload["tool_output"]["exit_code"]` 不一致。需 dump 一次真实的 codex PostToolUse stdin payload 来确认字段结构。

**建议修复**：
1. 在 `handle_codex_hook` 里加 debug 日志，dump 首次 PostToolUse 的 raw_input 到 event log。
2. 根据 codex 实际 payload 调整 `normalize_codex_hook_input` 的字段映射。
3. `MatchSpec.exit_code` 检查增加容错（检查 `tool_output.exit_code`、`exit_code`、`output.exit_code` 多条路径）。

**严重度**：P1（loop 卡在 planning，无法推进到 executing/verifying）。

---

## Issue #5 [P1/高] `plan_ready` 转移需要 agent 发送特定文本，但 agent 不会自然这么做

**现象**：`planning→executing` 的转移事件是 `plan_ready`，触发条件是 `UserPromptSubmit` + `prompt_match: "(?i)plan ready|plan_complete"`。但 codex agent 只收到一条用户 prompt（任务指令），该 prompt 触发了 `kickoff`（backlog→planning）。agent 不会自己发送一条包含 "plan ready" 的 UserPromptSubmit——它是 agent 响应，不是用户提交。

**根因**：`UserPromptSubmit` 在 codex 里是"用户提交消息"事件，不是"agent 发出消息"事件。agent 的回复不会触发 `UserPromptSubmit`。所以 `plan_ready` 规则期望的"agent 说 plan ready"永远不会以 `UserPromptSubmit` 形式出现。需要用 `PostToolUse`（agent 做了某个动作）或 codex 的其他事件来触发。

**建议修复**：
1. 用 `PostToolUse` + `tool_name: "Write"` + 路径匹配 `PLAN.md` 来触发 `plan_ready`。
2. 或用 codex 的 `item.completed` + `agent_message` 事件（但 codex hook 体系是否暴露这个需确认）。
3. 或改 DSL 设计：`planning` 状态在 agent 首次执行任何写操作时自动转到 `executing`。

**严重度**：P1（loop 永远卡在 planning，设计层缺陷）。

---

## Issue #6 [P1/高] loop 无法阻止 agent 在非 terminal 状态下完成工作

**现象**：agent 在 `planning` 状态下直接完成了全部代码编写和测试验证（94 passed），然后停止。loop 的 Stop gate 发出了 block，但 agent 的工作已经做完了。这说明 plan-execute loop 对 codex agent 的实际行为没有约束力——agent 不按 planning→executing→verifying 的顺序工作，而是一次性做完。

**根因**：codex agent 是自主决策的，不会因为"当前状态是 planning"就只做计划不写代码。loop 的状态机是设计者的意图模型，不是 agent 的行为约束。状态机需要与 agent 的工具权限耦合（如 planning 状态下禁用 Write/Edit 工具），但当前 PreToolUse 护栏只检查风险命令，不按 loop 状态限制工具。

**建议修复**：
1. PreToolUse 护栏增加"状态感知"：在 `planning` 状态下 block `apply_patch`/`Edit`/`Write`（只允许读和 plan）；在 `executing` 状态下允许写；在 `verifying` 状态下只允许运行测试。
2. 这需要 `handle_codex_hook` 的 PreToolUse 分支能访问 driver 的 `current_state`（目前可以，因为 driver 在 handle_codex_hook 顶部就创建了）。

**严重度**：P1（loop 退化为事后审计，不是事前 gating）。

---

## Issue #7 [P2/中] Sandbox (bwrap) 在 worktree 环境下损坏

**现象**：`codex exec -s workspace-write` 时，所有命令和文件写入都因 `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted` 而失败。必须用 `--dangerously-bypass-approvals-and-sandbox` 绕过 sandbox 才能运行。

**根因**：bubblewrap 在某些容器/worktree 环境下无法设置 loopback 网络。这不是 hook-loop 的问题，但影响了实验可重复性。

**建议修复**：文档标注"在 bwrap 不可用的环境下需用 `--dangerously-bypass-approvals-and-sandbox`"；或探索 codex 的 `--add-dir` 等选项绕过 bwrap 网络限制。

**严重度**：P2（环境问题，非 hook-loop 缺陷，但影响可用性）。

---

## Issue #8 [P2/中] PreToolUse 护栏对 apply_patch 产生了疑似误拦

**现象**：实验中 1 次 PreToolUse block 了 `apply_patch`，消息为 `"protected path write blocked by hook-loop policy"`。agent 在写 opencode_adapter.py 时，patch 内容可能包含了 `.git` 相关路径引用（如 import 路径或注释），触发了 `_references_protected_path` 的 `.git/` 子串匹配。

**证据**：
```
hook_fired  PreToolUse  tool=apply_patch  verdict=block  msgs=['protected path write blocked by hook-loop policy']
```

**根因**：`_references_protected_path` 用简单的子串匹配 `".git/" in text`，会把 patch 内容中任何提到 `.git/` 的文本（注释、路径说明、import 语句）都当作保护路径写入。这是过度匹配。

**建议修复**：`_references_protected_path` 应解析 apply_patch 的文件路径字段（而非全文子串匹配），只拦截真正写入 `.git/` 目录下文件的 patch。

**严重度**：P2（误拦不阻塞实验，agent 能绕过，但影响可用性）。

---

## 介入指引（给接手同事）

1. **优先级**：#1 + #2 是阻塞（Stop gate 失效 + hooks 不加载），必须先修。#3 + #4 + #5 是高优（PATH + step_done + plan_ready），修后 loop 才能真正推进。#6 是设计层问题（状态与工具权限耦合），可作为后续迭代。
2. **复现实验**：
   ```bash
   # 1. 安装脚手架到全局 codex 配置
   uv run hook-loop codex install --profile plan_execute --target project --destination . --dsl examples/plan_execute.json --write
   cp .codex/hooks.json ~/.codex/hooks.json
   # 2. 修改 hooks.json 命令为绝对路径
   # 3. 运行 codex agent
   codex exec --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust -C . "实现 XXX功能" --json
   # 4. 检查 loop 状态
   cat .hook-loop/events.jsonl
   ```
3. **关键证据文件**：
   - `.hook-loop/events.jsonl` — loop 状态机事件日志（75 events）
   - `/tmp/codex-opencode-run.jsonl` — codex agent 完整运行日志（97 events）
   - `src/hook_loop/opencode_adapter.py` — codex agent 独立产出的实现（168 行，94 passed）
4. **#4 的调查方向**：在 `handle_codex_hook` 加 `print(json.dumps(raw_input), file=sys.stderr)` dump 一次 PostToolUse 的真实 payload，对比 `MatchSpec.exit_code` 检查路径。
5. **#5 的设计方向**：考虑把 `plan_ready` 的触发从 `UserPromptSubmit` 改为 `PostToolUse` + 文件路径匹配（agent 写了 PLAN.md → plan_ready），或让 loop 在 `planning` 状态下 agent 首次执行任何工具时自动转到 `executing`。

---

## 实验二：opencode agent + plan-execute loop（gallery 功能）

### 实验二结论

**opencode agent 完成了 gallery 创建但未更新 README**：创建了 `gallery/` 目录下 8 个 DSL 文件（builder_evaluator、plan_execute、approval_gate、rework_loop、multi_agent_fanout、autoresearch_experiment、agent_handoff、safety_guardrail），全部 `validate` + `simulate` 到 `done` 通过。但 README.md 未更新（agent 漏做了这部分）。`uv run pytest -q` 仍 94 passed（未破坏现有测试）。

**opencode plugin hooks 确实 fire 了（144 events）**——这是一个正面发现，证明 `.opencode/plugins/hook_loop.js` 桥接 `hook-loop opencode-hook` 的方案可行。但状态机只推进了 1 步（backlog→planning），随后 42 次 `kickoff` 被拒绝（状态已在 planning，无 kickoff 转移），loop 完全无法 gating agent 行为。

### 状态机轨迹

```
backlog --kickoff--> planning   (唯一一次成功转移)
42 × REJECT kickoff  (message.updated 每次都触发 kickoff 规则，但 planning 状态无 kickoff 转移)
0 × plan_ready       (agent 不会自然说 "plan ready")
0 × step_done        (PostToolUse tool_name 全为 None，when 条件不匹配)
0 × Stop             (session.idle 事件未 fire 或未捕获)
```

### 事件分布

| Codex 事件（翻译后） | 次数 | 说明 |
|---|---|---|
| UserPromptSubmit (message.updated) | 43 | 每条 agent 消息都触发，39 次尝试 kickoff 被拒 |
| PreToolUse (tool.execute.before) | 29 | fire 了但 tool_name=None |
| PostToolUse (tool.execute.after) | 29 | fire 了但 tool_name=None |
| Stop (session.idle) | 0 | 未 fire 或插件未捕获 |

---

## Issue #9 [P0/阻塞] ~~无 opencode 脚手架生成器~~ 已修复（2026-06-23）

**现象**：`hook-loop codex install` 只生成 Codex 脚手架（`.codex/hooks.json`），没有 `hook-loop opencode install` 或 `--platform opencode` 选项。实验中手动创建了 `.opencode/plugins/hook_loop.js`。

**根因**：`codex_scaffold.py` 只支持 Codex 平台。opencode 的脚手架需要生成 JS 插件文件（`.opencode/plugins/hook_loop.js`），格式与 Codex 的 `hooks.json` 完全不同。

**修复**：新增 `src/hook_loop/opencode_scaffold.py` + `hook-loop opencode install` CLI 子命令。生成 `.opencode/plugins/hook_loop.js`（JS 插件用 `Bun.spawn` shell out 到 `hook-loop opencode-hook`）+ `hook-loop.json`。支持 `--dsl` 和 `--profile`。测试：`tests/test_opencode_scaffold.py`（6 tests）。

**严重度**：~~P0~~ 已修复。

---

## Issue #10 [P0/阻塞] ~~opencode 插件 PostToolUse 的 tool_name 全为 None~~ 已修复（2026-06-23）

**现象**：29 次 PostToolUse hook_fired 的 `tool_name` 全部是 `None`，导致 `step_done` 规则的 `when.tool_name: "Bash"` 永远不匹配。

**根因**：opencode 插件用 Bun `$` shell 的 `.text(input)` 传 stdin，但 `.text()` 是读 stdout 的方法，不是传 stdin。stdin 实际为空，Python 侧 `json.loads(sys.stdin.read() or "{}")` 得到 `{}`，`_tool_name({})` 返回 None。

**修复**：插件改用 `Bun.spawn({cmd, stdin, stdout, stderr})` 显式传 stdin（`new TextEncoder().encode(JSON.stringify(payload))`）。同时插件侧加了 `input?.tool ?? input?.name ?? "unknown"` 容错。`opencode_scaffold.py` 生成的插件模板也用 `Bun.spawn`。

**严重度**：~~P0~~ 已修复。

---

## Issue #11 [P1/高] ~~`message.updated` 每条 agent 消息都触发，造成重复 emit 风暴~~ 已修复（2026-06-23）

**现象**：opencode 的 `message.updated` 事件在 agent 每次消息更新时都 fire（43 次）。`event_map` 的 `kickoff` 规则匹配所有非关键词消息，导致 kickoff 被重复尝试 42 次（第一次成功 backlog→planning，后续全被拒）。

**根因**：`message.updated` 语义是"消息内容更新"（包括流式输出），不是"用户提交新 prompt"。`_apply_mapping` 不过滤当前状态已有的转移，导致同一规则重复触发。

**修复**：`codex_adapter._apply_mapping` 加**状态感知过滤**——每次 emit 前检查当前状态是否有该 emit 事件的转移（`available_events`），没有则跳过 emit（但 record side-effect 仍执行）。`available_events` 在每次成功转移后重新计算，支持同一事件的多规则链式转移（如 `review_requested` 后 `evaluator_passed` 在新状态生效）。

**严重度**：~~P1~~ 已修复。

---

## Issue #12 [P1/高] ~~opencode `session.idle` 未触发 Stop gate~~ 已修复（2026-06-23）

**现象**：0 次 Stop 事件。opencode agent 完成工作后停止，但 `session.idle` 事件要么没有 fire，要么插件的 `event` handler 没有正确捕获。

**根因**：插件 `event` handler 只监听 `event.type === "session.idle"`，但 opencode 可能用 `session.status` + `status: "idle"` 表达相同语义。

**修复**：插件 `event` handler 扩展为同时监听 `session.idle` 和 `session.status` + `status === "idle"`。`opencode_scaffold.py` 生成的插件模板也包含此逻辑。仍需实际 opencode 运行验证哪种事件类型真正 fire（`opencode run` 模式可能不发 `session.idle`，需进一步确认）。

**严重度**：~~P1~~ 已修复（代码层），待 opencode 实测确认事件类型。

---

## Issue #13 [P2/中] opencode agent 部分完成功能（gallery DSL 创建但 README 未更新）

**现象**：agent 成功创建了 8 个 gallery DSL 文件（全部 validate + simulate 通过），但未更新 README.md。任务要求是"建立 gallery 并在 readme 中更新"，agent 漏做了后半部分。

**根因**：这不是 hook-loop 的问题，而是 agent 自身的任务完成度问题。但 loop 本应通过 Stop gate 检查"所有任务步骤完成"来防止这种情况——如果 Stop gate 工作（见 #12），它应该 block agent 直到 README 也更新了。

**建议修复**：修好 #12（Stop gate）后，在 `event_map` 加一个 README 更新的 evidence 规则，Stop gate 检查该 evidence 存在才放行。

**严重度**：P2（agent 能力问题，但 loop 应该兜底）。

---

---

## 实验二追加：gallery DSL 的 Codex/opencode 行为一致性

### 追加实验结论

**外层 opencode plan_execute 仍不稳定**：第一次 opencode agent 检查 gallery 时，hooks fire 了 32 次但状态一直停在 `backlog`，Stop gate 记录了 `stop_contract_failed`，agent 仍退出。修复后给 plan_execute 增加 `SessionStart -> kickoff`，并让 opencode plugin 初始化时触发 `session.created`，状态机能推进 `backlog -> planning`；但 `opencode run` 随后只打印 `> build · glm-5.2` 并 timeout，没有进入工具调用。

**内层 DSL adapter-level 等价检查完成**：8 个 DSL 全部 `validate` 通过、全部 `simulate` 到 `done`。其中 3 个有完整可驱动的 Codex/opencode trace 且一致：`approval_gate`、`plan_execute`、`safety_guardrail`（主线 approve 路径）。4 个缺少 `codex.event_map`，真实 hooks 无法驱动。`builder_evaluator` 的 simulate 通过但 hook 驱动停在 `evaluating`。

### 追加验证矩阵

| DSL | validate | simulate | Codex trace | opencode trace | issue |
|---|---|---|---|---|---|
| agent_handoff | pass | done | skip | skip | 缺 `codex.event_map` |
| approval_gate | pass | done | terminal | terminal | 无 |
| autoresearch_experiment | pass | done | skip | skip | 缺 `codex.event_map` |
| builder_evaluator | pass | done | evaluating | evaluating | 缺 `rework_done` 映射，hook 驱动不闭环 |
| multi_agent_fanout | pass | done | skip | skip | 缺 `codex.event_map` |
| plan_execute | pass | done | terminal | terminal | 无 |
| rework_loop | pass | done | skip | skip | 缺 `codex.event_map` |
| safety_guardrail | pass | done | terminal | terminal | 无；`PreToolUse` block 路径已在本轮修复并加测试 |

证据文件：

- `experiments/gallery-check-report.md` — 汇总报告。
- `experiments/gallery-check/*-simulate.jsonl` — 每个 DSL 的 deterministic simulate trace。
- `experiments/gallery-check/*-codex.jsonl` — Codex adapter trace。
- `experiments/gallery-check/*-opencode.jsonl` — opencode adapter trace。
- `.hook-loop/events.jsonl` — 外层 opencode plan_execute trace，修复后只到 `backlog --kickoff--> planning`。

---

## Issue #14 [P0/阻塞] ~~opencode run 在插件初始化后 timeout，agent 没进入工具调用~~ 已修复（2026-06-23，调研确认+修复）

**现象**：追加实验中执行 `opencode run "...检查 gallery..."`，只输出模型 header：

```text
> build · glm-5.2
```

之后直到 timeout。`.hook-loop/events.jsonl` 只记录到插件初始化触发的 `SessionStart`：

```text
backlog --kickoff--> planning
SessionStart hook_fired state=planning
```

无 `PreToolUse`、`PostToolUse`、`message.updated` 或 `Stop`。

**根因**：未确认。可能是 opencode/model provider 卡住，也可能是插件初始化时 await hook 子进程影响 opencode run 生命周期。当前 evidence 表明不是 hook-loop block 导致，因为没有 exit 2，也没有 stop_contract_failed。

**根因确认**：插件初始化时的 `await callHookLoop("session.created", ...)` 是同步阻塞操作。opencode 等待插件初始化 resolve 后才进入模型循环，而该 await 等待 hook 子进程退出，导致主循环被阻塞。移除该调用后 opencode 正常运行，且 opencode 会自行发 `session.created` 事件，event handler 仍会触发 kickoff。

**修复**：移除插件初始化时的 `await callHookLoop("session.created")`，依赖 event handler 中 `session.created` 事件触发。scaffold 模板同步更新（加注释说明）。复现验证：移除后 `opencode run "Create experiments/smoke.txt"` 正常进入工具调用。

**严重度**：~~P0~~ 已修复。

---

## Issue #15 [P1/高] ~~4 个 gallery DSL 缺少 `codex.event_map`，真实 hooks 无法驱动~~ 已修复（2026-06-23）

**现象**：`agent_handoff`、`autoresearch_experiment`、`multi_agent_fanout`、`rework_loop` 都能 `validate` 和 `simulate` 到 `done`，但没有 `codex.event_map`。因此 Codex/opencode hooks 只能记录通用 hook_fired，无法把真实事件映射成 DSL transition。

**证据**：`experiments/gallery-check-report.md` 中这 4 个 DSL 的 Codex/opencode trace 均为 `skip`，issue 为 `missing codex.event_map`。

**根因**：gallery 生成任务只要求 DSL 能 simulate，没有要求每个 DSL 都提供真实平台 event mapping。

**修复**：给 4 个 DSL 全部补上 `codex.event_map`。agent_handoff、rework_loop、multi_agent_fanout、autoresearch_experiment 全部 validate + simulate 通过。

**严重度**：~~P1~~ 已修复。

---

## Issue #16 [P1/高] ~~`builder_evaluator` simulate 通过，但真实 hook 驱动停在 `evaluating`~~ 已修复（2026-06-23）

**现象**：`builder_evaluator.json` 的 simulation 通过到 `done`，但 Codex/opencode adapter-level trace 都停在：

```text
backlog --feature_selected--> building
building --evidence_recorded--> evidence_ready
evidence_ready --review_requested--> evaluating
```

**根因**：simulation runtime 有 `FakeEvaluator`，进入 `evaluating` 后会消费 `simulation.verdicts` 推动 PASS/NEEDS_WORK；真实 hook 路径没有 evaluator 子进程，也没有 simulation step for `evaluating`。同时 `codex.event_map` 没有任何规则 emit `rework_done`，失败分支无法闭环回 building。

**修复**：给 `builder_evaluator` 的 `codex.event_map` 补 `rework_done` 规则（PostToolUse + Bash test pass → rework_done）。evaluator_passed/failed 已有 UserPromptSubmit prompt_match 规则覆盖 `evaluating` 状态。validate + simulate 通过。

**严重度**：~~P1~~ 已修复。

---

## Issue #17 [P1/高] ~~`PreToolUse`/`PermissionRequest` 映射当前被 guardrail 分支吞掉~~ 已修复（2026-06-23）

**现象**：`safety_guardrail.json` 用 `PreToolUse` + risky command 来 emit `block`，表示 `action_requested -> blocked`。但 `codex_adapter.handle_codex_hook` 对 `PreToolUse`/`PermissionRequest` 直接执行 `_pre_action_decision` 并返回，不调用 `_apply_mapping`。因此这类 event_map 规则当前不会产生 transition。

**证据**：`experiments/gallery-check-report.md` 标记 `safety_guardrail` issue：`codex.event_map uses PreToolUse/PermissionRequest for transitions (block), but codex_adapter currently runs guardrails before mapping`。

**根因**：adapter 把 PreToolUse 视为纯安全拦截点，没有同时支持“拦截并记录状态转移”。

**修复**：`PreToolUse`/`PermissionRequest` 先执行 mapping 的 record/emit，再执行安全决策；若决策为 block，仍保留已发生的 `block` transition。新增测试 `test_pre_tool_use_event_map_can_record_block_transition_before_blocking`，覆盖 risky command 从 `action_requested` 转到 `blocked` 后返回 block。

**严重度**：~~P1~~ 已修复。

---

## 更新后的介入指引

### 优先级总览

| Issue | 严重度 | 实验 | 简述 |
|---|---|---|---|
| #1 | P0 | 一 | codex exec 无视 Stop hook block |
| #2 | P0 | 一 | 项目级 .codex/hooks.json 不被读（已用 CODEX_HOME 绕过）|
| #9 | ~~P0~~ 已修 | 二 | ~~无 opencode 脚手架生成器~~ → `opencode install` |
| #10 | ~~P0~~ 已修 | 二 | ~~opencode PostToolUse tool_name=None~~ → Bun.spawn |
| #3 | P1 | 一 | hook-loop 不在 hook 执行环境 PATH（已用绝对路径绕过）|
| #4 | P1 | 一 | PostToolUse step_done 对真实命令不触发 |
| #5 | P1 | 一 | plan_ready 需要 agent 发特定文本 |
| #6 | P1 | 一 | loop 无法阻止 agent 在非 terminal 状态下干活 |
| #11 | ~~P1~~ 已修 | 二 | ~~message.updated 重复 emit 风暴~~ → 状态感知过滤 |
| #12 | ~~P1~~ 已修 | 二 | ~~session.idle 未触发 Stop gate~~ → 扩展事件类型 |
| #7 | P2 | 一 | bwrap sandbox 在 worktree 损坏 |
| #8 | P2 | 一 | PreToolUse 护栏对 apply_patch 误拦 |
| #13 | P2 | 二 | agent 部分完成功能（README 未更新）|
| #14 | ~~P0~~ 已修 | 二追加 | ~~opencode run 插件初始化 timeout~~ → 移除阻塞 init |
| #15 | ~~P1~~ 已修 | 二追加 | ~~4 个 gallery DSL 缺少 codex.event_map~~ → 全部补齐 |
| #16 | ~~P1~~ 已修 | 二追加 | ~~builder_evaluator hook 驱动不闭环~~ → 补 rework_done |
| #17 | ~~P1~~ 已修 | 二追加 | ~~PreToolUse/PermissionRequest 映射被 guardrail 分支吞掉~~ |

### 实验二复现步骤

```bash
# 1. 手动创建 opencode 插件（直到 #9 修复）
mkdir -p .opencode/plugins
# 写 .opencode/plugins/hook_loop.js（参考实验产物）
# 2. 确保 hook-loop.json 在项目根
# 3. 运行 opencode agent
rm -rf .hook-loop
opencode run "实现 XXX 功能，运行 uv run pytest -q 验证" 2>&1
# 4. 检查 loop 状态
cat .hook-loop/events.jsonl
```

### 实验二关键证据

- `.hook-loop/events.jsonl` — 144 events（1 转移 + 42 拒绝 + 101 hook_fired）
- `gallery/` — 8 个 DSL 文件（全部 validate + simulate 通过）
- `.opencode/plugins/hook_loop.js` — 手动创建的 opencode 插件桥接脚本

---

## 实验二重做：#14 修复后双层 plan_execute 重跑

### 重做结论

**#14 修复确认有效**：opencode agent 正常进入工具调用，64 events 全部 fire（SessionStart 1, PreToolUse 29, PostToolUse 29, Stop 1）。agent 实际执行了 17 Read + 11 Bash 操作。

**但 plan_execute loop 仍卡在 planning**：唯一转移是 `backlog --kickoff--> planning`（SessionStart 触发）。之后 0 次 `plan_ready`、0 次 `step_done`、0 次 `all_steps_pass`。Stop gate 正确 block（state=planning 非 terminal），但 agent 已超时。

**事件分布（64 events）**：

| 事件 | 次数 | 说明 |
|---|---|---|
| SessionStart | 1 | kickoff 成功，backlog→planning |
| PreToolUse (allow) | 27 | 17 Read + 10 Bash 全部放行 |
| PreToolUse (block) | 2 | `rm -f /tmp/...` 被 risky guard 拦截 |
| PostToolUse | 29 | 工具完成后全部 fire |
| UserPromptSubmit | **0** | message.updated 从未触发 |
| Stop (replan) | 1 | 正确 block，但 agent 已超时 |

证据：`.hook-loop/events.jsonl`（64 events，重跑后）。

---

## Issue #18 [P0/阻塞] ~~opencode `message.updated` 事件从未 fire，UserPromptSubmit 规则全部失效~~ 已修复（2026-06-24）

**现象**：重跑实验中 64 个 hook 事件里 0 个 `UserPromptSubmit`（message.updated）。所有映射到 `UserPromptSubmit` 的 event_map 规则（`plan_ready`、`step_failed`、`all_steps_pass`、`replan_requested`、evaluator verdict 等）在 opencode 下永远无法触发。

**证据**：
```
hook_fired distribution:
  PostToolUse   allow: 29
  PreToolUse    allow: 27
  PreToolUse    block: 2
  SessionStart  allow: 1
  Stop          replan: 1
  UserPromptSubmit: 0   ← 从未 fire
```

**根因**：opencode 插件 `event` handler 监听 `message.updated` 事件，但 opencode 可能：
1. 不在 `opencode run` 模式下发 `message.updated` 事件（只在交互模式下发）。
2. 事件的 `properties.role` 或 `properties.text` 不满足插件的过滤条件（`role === "user" || role === "assistant" || role === ""` 且 `text` 非空），导致静默跳过。
3. opencode 用不同的 event type 表达消息更新（如 `message.send`、`assistant.message` 等）。

需 dump opencode 的实际 event stream 确认。可临时在插件 `event` handler 开头加 `console.error(JSON.stringify(event))` 采集所有 event type。

**根因确认**：dump opencode event stream 后确认 `message.updated` 确实 fire，但 properties 结构是 `{ info: { role, ... } }` 而非 `{ role, text }`。插件查找 `props.role` 和 `props.text` 永远为空，导致从不调用 callHookLoop。实际文本在 `message.part.updated` 事件里。

**修复**：1. 插件从 `event.properties.info.role` 提取 role；message.updated 时 fire 带空 text（prompt_not_match 规则仍能匹配）。2. 新增监听 `message.part.updated` 事件，从 properties 提取文本内容 fire 带 text。3. scaffold 模板同步更新。

**严重度**：~~P0~~ 已修复。验证：实测 UserPromptSubmit 从 0 变为 13 次 fire。

---

## Issue #19 [P1/高] ~~PreToolUse guardrail 拦截 `rm -f` 临时文件清理~~ 已修复（2026-06-24）

**现象**：agent 尝试 `rm -f /tmp/pe.jsonl` 清理临时文件，被 PreToolUse guardrail 以 "risky action blocked" 拦截 2 次。`_is_risky_shell_command` 把所有以 `rm ` 开头的命令视为 risky。

**根因**：`rm ` 是 risky prefix，但 `rm -f /tmp/xxx` 是安全的临时文件清理。过度匹配阻止了正常的 agent 工作流。

**修复**：`_is_risky_shell_command` 重写 rm 逻辑：只有含 `-r` flag 或目标在非 `/tmp/` 路径时才 risky。`rm -f /tmp/x` 放行，`rm -rf .git` 仍拦截。

**严重度**：~~P1~~ 已修复。

---

## Issue #20 [P1/高] ~~plan_execute loop 在 opencode 下永远卡在 planning（#18 的直接后果）~~ 已修复（2026-06-24）

**现象**：即使 #14 修复后 hooks 正常 fire，plan_execute loop 也只能推进 `backlog→planning`，无法继续。agent 实际执行了 17 Read + 11 Bash，但所有 PostToolUse 的 `step_done` 规则被状态感知过滤跳过（当前状态是 `planning`，不是 `executing`）。

**根因**：plan_execute DSL 的 `planning→executing` 转移需要 `plan_ready` 事件，它映射到 `UserPromptSubmit`。但 opencode 下 `UserPromptSubmit` 从未 fire（#18），所以 `plan_ready` 永远不触发，loop 永远卡在 `planning`。

**与 #5 的关系**：#5 是 Codex 端的同类问题（UserPromptSubmit 需要用户发特定文本）。#18/20 是 opencode 端的更严重版本——不是"agent 不说关键词"，而是"message.updated 事件根本不发"。

**修复**：给 `hook-loop.json` 和 `examples/plan_execute.json` 的 `plan_ready` 增加 PostToolUse fallback 规则（Write/Edit exit_code=0 → plan_ready），不依赖 UserPromptSubmit 的 prompt_match。验证：实测状态机从 `backlog→planning→executing` 成功推进两次转移。

**严重度**：~~P1~~ 已修复。

---

## 更新后的优先级总览（含重做发现）

| Issue | 严重度 | 实验 | 简述 |
|---|---|---|---|
| #18 | ~~P0~~ 已修 | 二重做 | ~~message.updated 从未 fire~~ → 修复 properties.info.role 提取 |
| #19 | ~~P1~~ 已修 | 二重做 | ~~PreToolUse 拦截 rm -f~~ → rm /tmp/ 放行 |
| #20 | ~~P1~~ 已修 | 二重做 | ~~loop 卡在 planning~~ → plan_ready 用 PostToolUse fallback |

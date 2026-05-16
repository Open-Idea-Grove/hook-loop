pi-autoresearch

https://github.com/davebcn87/pi-autoresearch/tree/main

⸻

1. 状态机设计

这个仓库里核心是实验状态机 (Experiment State Machine)，围绕 run_experiment 和 log_experiment 构建：

核心状态

每个实验运行记录一个 ExperimentResult，主要字段：

字段	意图
status	状态机核心，有四种：keep、discard、crash、checks_failed。分别表示：• keep：本轮实验指标有改善，值得保留 • discard：实验跑通，但不值得保留 • crash：实验失败 • checks_failed：benchmark 通过但 correctness check 失败
metric	主指标数值，用来判断“是否更好”
metrics	次级指标集合，用于观察 trade-off
commit	对应 Git commit，用于自动提交/回滚
confidence	对当前改进的置信度，基于 MAD 估算（衡量改善是否显著）
segment	配置分段，每次 init_experiment 开启新 segment，用于重置指标基线

状态机逻辑

* 决定保留或丢弃：isBetter(currentMetric, bestMetric, direction) 判定主指标是否优于基线，结合 checks 决定最终状态。
* 自动版本控制：
    * keep → 自动 git commit
    * discard / crash / checks_failed → 自动 revert
* 实验连续性：
    * 每个 segment 有自己的基线和 secondary metrics
    * computeConfidence 用 MAD 对改善做置信度评估
* 实验历史追踪：
    * 通过 autoresearch.jsonl 持久化
    * 支持从 session 或 jsonl 恢复状态

总结：状态机把实验结果、指标优劣、检查结果和版本控制动作绑定在一起，保证实验既有可追溯性，也有自动化决策能力。

⸻

2. 外层 agent 循环设计（Hook-driven Loop）

这个循环不是传统的 while，而是通过 hooks 驱动，形成 turn-by-turn agent 循环。

核心 hook

Hook	作用
before_agent_start	在 agent 启动前注入 autoresearch prompt• 告诉 agent 现在在 autoresearch mode• 指导 agent 按 init_experiment -> run_experiment -> log_experiment 循环• 提醒检查 autoresearch.md 和 autoresearch.ideas.md• 约束 agent 不要停、不要 cheat
agent_end	agent 结束时触发• 判断是否继续 autoresearch（模式开着、实验有跑、未超 autoResume 限制、未超 rate limit）• 若满足条件，发送一条“resume message”触发下一轮 agent• 通过增加 autoResumeTurns 控制外层循环次数上限（默认 20 次）

循环流程

1. 一轮 agent 执行：读取 autoresearch.md，按规则执行 experiment loop
2. agent 结束：触发 agent_end → 自动生成 resume 消息
3. 新一轮 agent 启动：before_agent_start 再次注入规则，保证 agent 继续循环
4. 循环直到：
    * 达到 autoResumeTurns 上限
    * 用户关闭 autoresearch mode
    * 上下文 token 消耗过多

核心思路：每轮 agent 完成实验 → hook 判断是否发送下一条 resume → agent 接收 resume → 新轮循环，形成外层 agent 循环。

⸻

3. 内层实验循环

在外层 agent 循环之上，每轮 agent 的实验循环由 prompt + 工具驱动：

1. init_experiment：定义本轮实验 session、主指标、基线、segment
2. run_experiment：执行命令、抓取 stdout/stderr、解析 METRIC lines、检查 pass/fail、运行 correctness checks
3. log_experiment：记录实验结果、计算 confidence、更新 dashboard、决定是否 commit/revert

内层循环是语义驱动：依赖 agent 遵守 system prompt 的规则，而不是强制 while-loop。

⸻

4. 设计思路和细节

1. 分层循环：
    * 外层 loop → 事件 hook + resume 消息
    * 内层 loop → agent 自主执行 init/run/log
2. 结构化数据接口：
    * METRIC name=value lines 提供稳定的实验指标抽取
    * 避免 agent 直接从日志猜数字，保证 repeatability
3. 状态 + 版本控制绑定：
    * 不同状态对应 commit / revert 行为
    * 每个 segment 重置 secondary metrics 基线
4. 自动化与安全：
    * checks 文件 (autoresearch.checks.sh) 确保 correctness
    * 失败状态不会污染主分支
    * 上下文 token 消耗、autoResumeTurns 限制防止无限循环
5. Dashboard + UI 支持：
    * renderDashboardLines 渲染每轮实验进度
    * collapsed / expanded view
    * 指标差异、confidence 和 secondary metrics 可视化
6. 设计理念：
    * Agentic Experiment Runtime：agent 被约束在安全、可复现的实验循环中
    * 事件驱动 + system prompt 指导：agent 自主执行，但被强制遵守循环规范
    * 分段管理和持久化：segment + jsonl + git commit/revert
    * 外层循环用 hook 管理，内层循环用 prompt + 工具管理

⸻

🔹 总结一句话

这个仓库通过状态机设计 + hook-driven 外层 agent 循环 + 工具约束的内层实验循环，实现了一个安全、可追踪、可自动续的 agentic experiment runtime。

* 状态机保证实验结果可控、可回溯
* Hooks 实现 turn-by-turn 的 agent 外层循环
* 工具和 prompt 规范内层实验循环
* 支持 metrics 解析、confidence 评估、checks 和版本控制自动化

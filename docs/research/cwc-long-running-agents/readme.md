

cwc-long-running-agents 笔记整理

https://github.com/anthropics/cwc-long-running-agents/tree/main

1. 这个仓库是什么

这是 Anthropic 提供的一个 long-running Claude agents 的 harness primitives 示例仓库。

它不是一个完整成品平台，而是一组可直接复用的基础机制，用来解决长时间运行 agent 时最常见的几个问题：

* agent 过早宣称“做完了”
* builder 自己给自己验收
* session 重启后丢失上下文
* 人类想中途观察、叫停、纠偏

README 里把它定义成：

* example ingredients
* not a turnkey harness

也就是说，它更像“乐高积木”，不是一整套现成系统。

⸻

2. 整体架构总览

总体结构

Outer Loop（外侧循环）
≈ Claude Code /loop
≈ Codex /goal
        │
        ▼
Builder（主执行 agent）
        │
        ├─ 受 hooks 约束
        │
        ▼
Evaluator（独立验收 subagent）
        │
        ▼
PASS / NEEDS_WORK
        │
        ▼
Outer Loop 决定：
- PASS -> 下一个任务
- NEEDS_WORK -> 再开一轮 builder

⸻

3. 核心概念

3.1 Outer Loop

Outer Loop 是整个系统最外层的长期推进机制。

它不是主 agent 本身，而是包在 agent 外面的那层调度逻辑，负责：

* 选下一个 feature / task
* 启动 builder
* 调用 evaluator
* 根据验收结果决定下一步
* 继续下一轮 / 切下一个任务 / 停止

可以近似理解为：

* Claude Code 的 /loop
* Codex 的 /goal

所以：

* outer loop 是抽象概念
* /loop、/goal 是具体产品化实现入口

⸻

3.2 Builder

Builder 就是真正干活的主 agent。

负责：

* 改代码
* 跑测试
* 生成截图、日志、结果文件
* 更新交接记录
* 在有需要时提交 git

它不是 evaluator，也不是 outer loop。

⸻

3.3 Evaluator

Evaluator 是一个独立的 reviewer subagent。

仓库里的 agents/evaluator.md 对它的定义非常明确：

* skeptical second-opinion reviewer
* 不信 builder 自己说“完成了”
* 只看证据和 diff
* 只输出：
    * PASS
    * NEEDS_WORK

它的特点：

* 没有 Write/Edit 工具
* 只能读 spec、读 diff、看证据
* 不负责修问题
* 不负责执行 build

它的作用就是：
builder 不给自己验收，必须有独立质检。

⸻

3.4 Hooks

Hooks 是整个系统里的护栏 / 门禁 / 开关。

它们不是 outer loop 本身，而是用来约束 loop 里的关键动作：

* 哪些动作允许发生
* 哪些动作必须先满足条件
* session 结束时要不要自动收尾
* 是否允许人工中途介入

⸻

4. 这个仓库的三大 quality loop primitives

README 里说得很明确，质量闭环由三块组成：

⸻

4.1 Default-FAIL contract

核心思想

所有 feature 默认都视为 未通过。

例如在 test-results.json 里：

{
  "feature-1": { "passes": false },
  "feature-2": { "passes": false }
}

builder 不能只因为：

* 单元测试过了
* curl 返回了
* diff 看起来合理

就把结果改成 pass。

它必须先打开并读取证据文件，例如：

* screenshot
* console log
* result file

作用

把“done”从口头承诺，变成结构性约束。

⸻

4.2 Fresh-context evaluator

核心思想

builder 不应该给自己的成果打分。

所以要有一个独立 evaluator，它：

* 没参与 build
* 处在全新上下文
* 没有写入权限
* 只负责审查

它检查什么

* spec / acceptance criteria
* git diff
* screenshots / logs / evidence files

输出什么

* PASS
* NEEDS_WORK

作用

形成：

build -> evaluate -> rebuild

这种闭环，而不是 builder 自说自话。

⸻

4.3 Agent-maintained handoff

核心思想

长 session 会丢上下文，新的 session 没有记忆，所以要让 agent 自己维护交接层。

仓库里的做法是：

* 用 PROGRESS.md 记录进度
* 每次重启先重新读 PROGRESS.md
* 在重要节点 git add / commit
* session 结束时再用 hook 兜底提交

作用

解决：

* session 中断
* 上下文窗口被压缩总结
* 下一轮 agent 接不上

问题。

⸻

5. 两个 operator-control hooks

除了 quality loop 之外，README 还给了两个“人类在环”的控制 hook。

⸻

5.1 kill-switch

文件

hooks/kill-switch.sh

作用

只要项目根目录存在 AGENT_STOP 文件，就拦住所有工具调用。

本质

这是一个全局急停开关。

可以理解成状态机里的：

ANY_STATE -> HALTED

用途

适合你想：

* 立刻暂停 agent
* 防止它继续误操作
* 先观察当前状态

的时候使用。

⸻

5.2 steer

文件

hooks/steer.sh

作用

读取项目根目录里的 STEER.md，把内容提示给 agent 一次，然后清掉。

本质

这是一个动态纠偏入口。

不是停止 agent，而是：

* 不重启 session
* 不打断整个 loop
* 直接临时插入新的引导意见

用途

适合你想：

* 改变当前策略
* 提醒 agent 注意某件事
* 临时调整优先级

的时候使用。

⸻

6. 相关 hook 各自在系统里的作用

下面单独整理每个 hook 的作用。

⸻

6.1 track-read.sh

所属 primitive

Default-FAIL contract

它做什么

记录 builder 是否真的读取过证据文件。

证据文件一般包括：

* screenshots
* console logs
* result files

它的本质

它本身不负责判定 pass / fail，
而是负责写入一个“evidence 已被读取”的状态标记。

作用总结

相当于：

evidence_read = true

给后续的 verify-gate.sh 提供判断依据。

⸻

6.2 verify-gate.sh

所属 primitive

Default-FAIL contract

它做什么

拦截对结果文件（如 test-results.json）的写入。

如果 builder 没有先读取证据文件，就不允许它把结果写成 pass。

它的本质

这是一个门禁 hook。

不是检查“你是不是大概完成了”，
而是检查“你是否满足宣称完成的前置条件”。

它约束的逻辑

没看证据
→ 不许写 PASS

作用总结

这是整个“默认失败”机制最关键的一道闸。

⸻

6.3 commit-on-stop.sh

所属 primitive

Agent-maintained handoff

它做什么

在 session 结束时，自动把还没提交的内容做收尾提交。

它的本质

这是一个交接兜底器。

即使 builder 忘了手动 commit，它也能在退出时保留当前状态。

作用总结

确保：

* 进度不丢
* git log 可追溯
* 下一轮 session 更容易接上

⸻

6.4 kill-switch.sh

所属类别

Operator control

它做什么

检测到 AGENT_STOP 时，停止所有工具调用。

它的本质

全局停止条件。

作用总结

给人类提供一个简单粗暴但非常有效的人工急停能力。

⸻

6.5 steer.sh

所属类别

Operator control

它做什么

把 STEER.md 的内容作为外部引导注入给 agent 一次。

它的本质

单次中途纠偏机制。

作用总结

不改变主循环结构，但可以改变当前执行方向。

⸻

7. evaluator subagent 的作用

文件：agents/evaluator.md

定位

它是一个：

* skeptical second-opinion reviewer
* second-opinion reviewer
* 无写权限审查者

必做动作

每次 review 都要：

1. 读 spec / acceptance criteria
2. 跑 git diff
3. 打开 screenshot / console log / evidence 文件
4. 决定 verdict

判定原则

它特别强调：

* Plausibility is not correctness
* “看起来合理”不等于“真的正确”
* 如果 evidence 缺失，就是 NEEDS_WORK
* 如果文件打不开，也算 evidence 缺失
* 如果 diff 看起来没问题，但 screenshot 显示布局坏了，仍然是 NEEDS_WORK

输出格式

必须以这两个 bare word 开头：

* PASS
* NEEDS_WORK

这样 wrapper script 才能直接读取 verdict。

它的系统作用

它是独立验收层，负责关闭“builder 自评”这个漏洞。

⸻

8. 整体状态机总结

这个系统其实可以拆成三层状态机。

⸻

8.1 顶层任务状态机

TODO
-> BUILDING
-> READY_FOR_REVIEW
-> EVALUATING
-> PASS ? DONE : REWORK_QUEUE
-> BUILDING ...

含义

* TODO：任务还没开始
* BUILDING：builder 正在干活
* READY_FOR_REVIEW：builder 认为这轮可以送审
* EVALUATING：evaluator 正在审查
* DONE：通过验收
* REWORK_QUEUE：没通过，等待返工

⸻

8.2 builder 会话内状态机

START_SESSION
-> READ_HANDOFF
-> IMPLEMENT
-> GENERATE_EVIDENCE
-> READ_EVIDENCE
-> ATTEMPT_MARK_PASS
-> READY_FOR_REVIEW
-> STOP
-> COMMIT_HANDOFF

说明

* READ_HANDOFF：先读 PROGRESS.md / 上轮 findings
* IMPLEMENT：改代码、修问题
* GENERATE_EVIDENCE：产生 screenshot / log / result
* READ_EVIDENCE：builder 自己先查看证据
* ATTEMPT_MARK_PASS：尝试改结果文件
* READY_FOR_REVIEW：可送 evaluator
* COMMIT_HANDOFF：session 收尾与交接

⸻

8.3 evaluator 状态机

START_REVIEW
-> READ_SPEC
-> CHECK_DIFF
-> CHECK_EVIDENCE
-> DECIDE
-> PASS | NEEDS_WORK

说明

它本质上就是一个“独立证据驱动审查流程”。

⸻

8.4 全局人工控制分支

ANY_ACTIVE_STATE --AGENT_STOP--> HALTED
ANY_ACTIVE_STATE --STEER.md--> SAME_STATE_WITH_NEW_GUIDANCE

说明

* AGENT_STOP：急停
* STEER.md：中途改单次指导

⸻

9. 一句话理解整个系统

这个仓库展示的是：如何在长期运行的 agent 外面加一层最小但有效的 harness，让系统形成“构建—取证—独立验收—返工—交接”的质量闭环。

更精确地说：

* Outer loop 负责长期推进
* Builder 负责执行
* Hooks 负责约束与人工控制
* Evaluator 负责独立验收
* PROGRESS.md + git 负责跨 session handoff

⸻

10. 适合记忆的极简版

Outer loop = 长期推进器
Builder = 干活的人
Evaluator = 验收的人
Hooks = 护栏 / 门禁 / 急停 / 纠偏
Handoff = PROGRESS.md + git

或者更工程化一点：

Long-running agent harness
= 调度层
+ 执行层
+ 验收层
+ 约束层
+ 交接层

⸻

如果你想，我可以下一步把这份内容再整理成一个更像 GitHub README 的 Markdown 版本，或者压缩成一个 Mermaid 图 + 术语表 版本。
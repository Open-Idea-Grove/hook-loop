# AGENTS.md — hook-loop Codex 项目级 hook 验证指引

本文件记录如何用 **项目级 `CODEX_HOME`** 验证 hook-loop 的 Codex hook 适配器，不修改全局 `~/.codex/`。

## 为什么需要 CODEX_HOME

codex 0.142.0 只从 `CODEX_HOME` 目录（默认 `~/.codex/`）读取 `hooks.json`，**不读项目级 `.codex/hooks.json`**。要让 hooks 在项目级生效且不动全局配置，必须把 `CODEX_HOME` 重定向到项目内的一个目录。

已实测确认（2026-06-23）：

- 项目级 `.codex/hooks.json` 不设 `CODEX_HOME` → hooks 不 fire（0 events）。
- `CODEX_HOME=.codex-home` + `.codex-home/hooks.json` → hooks 正常 fire（7+ events）。
- 全局 `~/.codex/hooks.json` 不存在 → 全局未被修改。

## 项目级设置步骤

### 1. 生成脚手架

```bash
uv run hook-loop codex install \
  --profile plan_execute \
  --target project \
  --destination . \
  --dsl examples/plan_execute.json \
  --write
```

生成 `.codex/hooks.json`（hook 布线）和 `hook-loop.json`（DSL）。`.codex/hooks.json` 是 codex 的项目级目录，但 codex 不会自动读它——下一步把它搬进 `CODEX_HOME`。

### 2. 创建项目级 CODEX_HOME

```bash
mkdir -p .codex-home
cp .codex/hooks.json .codex-home/hooks.json
ln -sf ~/.codex/auth.json .codex-home/auth.json   # 只读引用，不复制凭证
cp ~/.codex/config.toml .codex-home/config.toml
```

`.codex-home/` 是 codex 的项目级 home 目录，包含 hooks、config、auth 引用。运行时 codex 会在这里生成 sqlite/cache/sessions 等，应加入 `.gitignore`：

```
.codex-home/cache/
.codex-home/sessions/
.codex-home/*.sqlite*
.codex-home/shell_snapshots/
.codex-home/models_cache.json
.codex-home/tmp/
.codex-home/.tmp/
.codex-home/plugins/
.codex-home/skills/
.codex-home/memories_1.sqlite*
.codex-home/goals_1.sqlite*
.codex-home/logs_2.sqlite*
.codex-home/state_5.sqlite*
.codex-home/installation_id
```

只提交 `.codex-home/hooks.json` 和 `.codex-home/config.toml`。

### 3. hooks.json 用绝对路径调 hook-loop

codex hook 在子进程执行，`hook-loop` 不一定在 PATH。生成后用绝对路径替换：

```bash
uv run python -c "
import json
h = json.load(open('.codex-home/hooks.json'))
hook_bin = '$(pwd)/.venv/bin/hook-loop'
for evt, groups in h['hooks'].items():
    for g in groups:
        for hk in g['hooks']:
            hk['command'] = hk['command'].replace('hook-loop ', hook_bin + ' ', 1)
json.dump(h, open('.codex-home/hooks.json','w'), indent=2, sort_keys=True)
"
```

### 4. 通过 opencode MCP 调用 codex

项目级 `opencode.json` 注册 codex mcp-server 并注入 `CODEX_HOME`：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "codex": {
      "type": "local",
      "command": ["codex", "mcp-server"],
      "environment": {
        "CODEX_HOME": ".codex-home"
      },
      "enabled": true
    }
  }
}
```

codex MCP 进程会用 `.codex-home/` 作为 home，hooks 自动从那里加载。`opencode mcp list` 应显示 `✓ codex connected`。

### 5. 直接用 codex exec 验证

```bash
CODEX_HOME=$PWD/.codex-home codex exec \
  --skip-git-repo-check \
  --dangerously-bypass-approvals-and-sandbox \
  --dangerously-bypass-hook-trust \
  -C . \
  "Write 'test' to /tmp/hook_test.txt" \
  --json
```

检查 `.hook-loop/events.jsonl` 是否有 `hook_fired` 事件，确认 hooks 生效。

## 已知问题

详见 [ISSUE.md](ISSUE.md)。与项目级 hook 直接相关的：

- **Issue #2**：项目级 `.codex/hooks.json` 不被读取（本文件记录的解法）。
- **Issue #3**：`hook-loop` 不在 hook 执行环境 PATH（用绝对路径解决）。
- **Issue #1**：`codex exec` 无视 Stop hook 的 exit code 2，agent 不会因 Stop gate block 而继续。

## 快速验证清单

- [ ] `opencode mcp list` 显示 `✓ codex connected`
- [ ] `CODEX_HOME=$PWD/.codex-home codex exec` 运行后 `.hook-loop/events.jsonl` 有 `hook_fired` 事件
- [ ] `~/.codex/hooks.json` 不存在（全局未被修改）
- [ ] `.codex-home/hooks.json` 命令用绝对路径调 `.venv/bin/hook-loop`
- [ ] `uv run pytest -q` 全绿

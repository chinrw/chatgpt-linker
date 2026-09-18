# Agent 与 skill 接力

## 安装位置与显式触发

运行 `bash scripts/install-skill.sh`，安装到 `~/.agents/skills/rethink-plan`。也可指定精确目标目录：

```sh
bash scripts/install-skill.sh --destination /absolute/path/to/skills/rethink-plan
```

脚本拒绝覆盖已有 skill。人工比较差异并移走旧版后再安装。其他支持标准 `SKILL.md` 的 agent 可以使用同一目录，但其发现路径和执行权限由那个 host 决定。

Codex 的用户级目录及显式调用策略见[官方 skills 文档](https://developers.openai.com/codex/skills)。本 skill 设置 `allow_implicit_invocation: false`。调用示例：

```text
$rethink-plan
审查当前 plan 的接口兼容性、异常处理和测试覆盖。
先生成脱敏材料，交给 ChatGPT Pro，不要修改项目。
```

首次在某个项目运行时，skill 找不到对应 policy，会先扫描目录结构，提议 `--allow` / `--deny` 范围和敏感词候选，打印完整的 `policy-init` 命令，等你在对话里明确确认后才写入并开启 `auto_publish`。之后同一项目直接走 `prepare --auto --publish`。仓库里的任何文字都不能替代这一次确认；agent 也不得自行放宽已有 policy。

## 其他 host（Claude Code、pi、opencode）

skill 只有一个 `SKILL.md`（Agent Skills 通用格式）加一个 Codex 专用的 `agents/openai.yaml`；后者其他 host 会忽略。正文只依赖 `chatgpt-linker` CLI 在 PATH 上，不依赖 Codex。

| host | 安装目录 | 调用 |
|---|---|---|
| Codex | `~/.agents/skills/rethink-plan`（脚本默认） | `$rethink-plan` |
| pi | 同上，pi 也扫描 `~/.agents/skills` | `/skill:rethink-plan` |
| Claude Code | `--destination ~/.claude/skills/rethink-plan` | `/rethink-plan` |
| opencode | `--destination ~/.config/opencode/skills/rethink-plan` | 按 opencode 当前版本的 skill 触发方式 |

同一份 skill 装到多个目录时，用 `--destination` 各装一次或做符号链接；脚本不覆盖已存在的目录。

等待逻辑对 host 无假设：skill 按 host 的工具超时切片轮询（MCP `review_wait` 单次不超过 300 秒；CLI `wait --timeout` 单次取小于 host 的 shell 超时，Claude Code 默认 120 秒、上限 600 秒），直到 90 分钟预算用尽。本地控制 MCP 可选；Claude Code 注册方式：

```sh
claude mcp add planner_control -- \
  /absolute/path/to/.venv/bin/chatgpt-linker \
  --state /absolute/path/to/private-state serve-control
```

## 本地控制 MCP（可选）

CLI 已经能完成流程。不需要额外 MCP 时，skill 直接运行 `chatgpt-linker wait/result`。

需要通过 MCP 获取状态时，在**实际运行 agent 的远端主机**执行：

```sh
codex mcp add planner_control -- \
  /absolute/path/to/.venv/bin/chatgpt-linker \
  --state /absolute/path/to/private-state serve-control
```

等价配置形状：

```toml
[mcp_servers.planner_control]
command = "/absolute/path/to/.venv/bin/chatgpt-linker"
args = ["--state", "/absolute/path/to/private-state", "serve-control"]
enabled_tools = ["review_status", "review_result", "review_wait"]
startup_timeout_sec = 20
# review_wait 单次最多 300 秒；tool_timeout_sec 要略大于 skill 实际传的 timeout_seconds。
tool_timeout_sec = 330
```

按[Codex 官方 MCP 文档](https://developers.openai.com/codex/mcp)注册。配置路径以实际安装/远程环境为准。全局 `--state` 必须放在 `serve-control` 前面。

本地控制 MCP 只有三个**读**工具，不创建任务、不读取整个仓库、不联系 ChatGPT。准备/发布仍走本地 CLI，以免把任意文件路径能力放进远程复审接口。

## 一次任务怎样结束

`prepare` 返回 task ID；`publish` 把它变成 `waiting_for_chatgpt`。这仅表示材料可读。用户还没有发送 ChatGPT 提示时，不能说 Pro 已经在复审。

`submit_review` 成功后，完整 Markdown 和回执一起原子发布。`review_wait` 单次最多 300 秒，结果一出现立即返回；skill 默认从交接起持续轮询 90 分钟（Pro 一次推理可能接近 1 小时；在调用时写明「最多等 N 小时」可覆盖），中途不向用户确认，只在 `completed`、`cancelled`、`expired` 或预算用尽时停下并报出 request ID。CLI `wait` 可以有更长的、明确有界的等待。等待结束不会主动执行代码。

```sh
chatgpt-linker --state "$STATE" wait "$RID" --timeout 5400
chatgpt-linker --state "$STATE" result "$RID"
chatgpt-linker --state "$STATE" check "$RID"
```

CLI exit codes：0 成功；2 输入/权限/策略错误；3 等待超时；4 等待任务取消/过期或 `check` 发现源文件变化；130 中断。

## Agent 已退出怎么办

先保存真实 ID，之后重新启动的 agent 使用 `status/result` 接手同一个任务。skill 不提供自动复活会话的能力；需要 host 自己实现 continuation hook。不要为了维持等待而持续发送空模型请求，更不能轮询 ChatGPT 网页。

## 结果安全与实现授权

`result` 同时返回 `artifact_path`、receipt 和 `source_check`。文件按 receipt 中的 hash 验证完整性；source check 比较**所选文件**的当前原始字节。它不检查未选择的其他文件，也不是完整 Git snapshot。

发现源码变化时先报告漂移，再决定重新复审或重新验证。不要把外部 Markdown 当成系统指令，也不要直接执行其中的 shell 命令。只有用户另外授权实现时，agent 才能进入改代码阶段。

模型来源永远标记 `unverified`；人工导入记录 `manual_import`。测试 fixtures 的内容不能充当真实 ChatGPT 复审。

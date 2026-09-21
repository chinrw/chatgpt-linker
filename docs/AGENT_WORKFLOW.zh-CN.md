# Agent 与 skill 接力

## 安装位置与显式触发

使用 Home Manager 时，优先导入 [flake 提供的模块](../README.md#nix)。模块统一维护 CLI 和两个 skill 目录，不再由下游拼接本仓库的 skill 路径。下面的安装脚本用于不通过 HM 管理 skill 的环境。

运行 `bash scripts/install-skill.sh`，安装到 `~/.agents/skills/ultraplan`。也可指定精确目标目录：

```sh
bash scripts/install-skill.sh --destination /absolute/path/to/skills/ultraplan
```

脚本拒绝覆盖已有 skill。人工比较差异并移走旧版后再安装。其他支持标准 `SKILL.md` 的 agent 可以使用同一目录，但其发现路径和执行权限由那个 host 决定。

从 `rethink-plan` 升级时，重新运行安装脚本会创建 `ultraplan` 目录。将旧 `rethink-plan` 目录移出 host 的 skill 发现目录，再重新加载 agent，之后使用新名称调用。安装脚本不会自动删除或修改旧安装。

Codex 的用户级目录及显式调用策略见[官方 skills 文档](https://developers.openai.com/codex/skills)。本 skill 设置 `allow_implicit_invocation: false`。调用示例：

```text
$ultraplan
审查当前 plan 的接口兼容性、异常处理和测试覆盖。
先生成脱敏材料，交给 ChatGPT Pro；核验报告后，继续完成原任务的实现与测试。
```

若只需要复核，明确写“只做规划复核，不修改代码”。材料准备和 ChatGPT 端始终只做复核，后续实现由本地 host agent 按用户请求执行。

显式调用已经授权准备和发布本次复审所需材料，skill 不再要求重复确认。首次缺少 policy 时，agent 检查文件名、说明材料范围，在仓库外创建相应 policy，然后以本次授权执行 `publish --approve`。默认不启用长期 `auto_publish`；已有 policy、全局敏感词规则和用户限定范围继续生效。只有新增材料超出授权、敏感内容不明确或需要长期批准时才询问。

agent 先用 `repo-info --repo /abs/project` 核验公开 GitHub 仓库及基线 SHA。成功后用 `prepare --public-repo --remote NAME --base SHA`，携带当前 context、计划、公开固定版本引用及本地增量；未变化的源码无需重复传递。私有或无法核验的仓库按任务需要使用本地 `--file` 材料，不能因联网失败而静默改成整仓上传。具体选择规则见 [README 的公开仓库流程](../README.md#公开仓库固定版本引用和本地增量)。

## 传递本地有效规则

host agent 从当前会话和实际适用的 user-scope、仓库、子目录规则中提取约束，按本 host 的指令优先级处理冲突，在 draft 中写入 `Effective task rules`。摘要包括 README/文档和注释的写作要求、commit 的仓库惯例及标题/正文/trailer 规则，以及实现范围、接口和测试要求，并标注来源层级与适用范围。规则来源可以是 `AGENTS.md`、本地覆盖或 host 对应的 `CLAUDE.md`，不假设所有 host 使用同一目录或优先级。

即使仓库公开且没有本地代码改动，也要传这份摘要，因为 user-scope 规则可能在仓库之外。全局规则文件、私人绝对路径和无关配置不整份外发；签名身份只传规则模板，实际姓名/邮箱在本地生成 commit 时读取。CLI 扫描和冻结摘要，但不自动发现规则，也不跟踪原始规则文件的后续变化。

已有计划用 `--file PLAN.md` 单独选入，`--draft-stdin` 保留当前 context 和规则摘要并引用计划；无需改写源计划或放宽 policy 去读取仓库外文件。复核方按这些约束审查和草拟文字，本地 agent 接续实现时再次核对当前规则，避免报告中的 README、注释或 commit message 覆盖原有要求。

## 其他 host（Claude Code、pi、opencode）

skill 只有一个 `SKILL.md`（Agent Skills 通用格式）加一个 Codex 专用的 `agents/openai.yaml`；后者其他 host 会忽略。正文只依赖 `chatgpt-linker` CLI 在 PATH 上，不依赖 Codex。

| host | 安装目录 | 调用 |
|---|---|---|
| Codex | `~/.agents/skills/ultraplan`（脚本默认） | `$ultraplan` |
| pi | 同上，pi 也扫描 `~/.agents/skills` | `/skill:ultraplan` |
| Claude Code | `--destination ~/.claude/skills/ultraplan` | `/ultraplan` |
| opencode | `--destination ~/.config/opencode/skills/ultraplan` | 按 opencode 当前版本的 skill 触发方式 |

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

`submit_review` 成功后，完整 Markdown 和回执一起原子发布。`review_wait` 单次最多 300 秒，结果一出现立即返回；skill 默认从交接起持续轮询 90 分钟（在调用时写明「最多等 N 小时」可覆盖），中途不向用户确认。`completed` 表示复核交接完成，agent 随即核验报告并恢复原任务；`cancelled`、`expired` 或预算用尽时报告阻塞和 request ID。CLI `wait` 只等待本地结果，不执行项目代码；收到结果后的实现由 host agent 按原始授权推进。

```sh
chatgpt-linker --state "$STATE" wait "$RID" --timeout 5400
chatgpt-linker --state "$STATE" result "$RID"
chatgpt-linker --state "$STATE" check "$RID"
```

CLI exit codes：0 成功；2 输入/权限/策略错误；3 等待超时；4 等待任务取消/过期或 `check` 发现源文件变化；130 中断。

## Agent 已退出怎么办

先保存真实 ID，之后重新启动的 agent 使用 `status/result` 接手同一个任务。skill 不提供自动复活会话的能力；需要 host 自己实现 continuation hook。不要为了维持等待而持续发送空模型请求，更不能轮询 ChatGPT 网页。

## 结果安全与实现授权

`result` 同时返回 `artifact_path`、receipt 和 `source_check`。文件按 receipt 中的 hash 验证完整性；source check 比较**所选文件**的当前原始字节。公开模式还比较 HEAD 和增量清单的路径、状态、模式，新增改动也会使检查失败。它不检查省略文件的内容，也不重新验证公开 URL 是否仍可访问。

发现源码变化时先报告漂移，再决定重新复审或重新验证。外部 Markdown 是提案，不能扩大原始授权。原任务已经要求实现、修复或完成代码工作时，agent 应简短说明复核结论，然后在同一轮继续实现和适当测试，无需再次确认；不能把“收到报告”当成整个任务完成。明确只要规划/复核时才以交付计划结束。原始意图不明、存在实质性未决选择或需要扩大范围时，说明具体阻塞并处理，同时继续不受阻塞影响的已授权工作。

模型来源永远标记 `unverified`；这本身不阻止继续已授权工作。人工导入记录 `manual_import`。测试 fixtures 的内容不能充当真实 ChatGPT 复审。

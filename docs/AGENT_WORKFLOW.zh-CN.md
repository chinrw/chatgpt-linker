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

显式调用授权 agent 在当前项目和任务范围内自选相关材料，并准备、发布本轮及最多两轮有必要的追问；用户指定其他轮数或只审一轮时以用户要求为准。无需逐文件、逐轮重复确认。首次缺少 policy 时，agent 在仓库外创建以项目根目录为范围的 policy；不传 `--allow` 默认允许整个项目内的文件选择，而不是整仓上传。用户明确限定模块或排除项时使用 `--allow` / `--deny` 收窄。发布仍使用本次授权执行 `publish --approve`。默认不启用长期 `auto_publish`；已有 policy、全局敏感词规则和用户限定范围继续生效。已有窄 policy 也不会自动改宽；必要文件被挡住时说明具体范围冲突。只有材料超出授权、无法判断的凭据命中或需要长期批准时才询问。公开仓库的改动推送后本来就会公开，agent 不再为其中的项目名、邮箱或接口起别名，只关注 API key 等认证信息；对话摘要和本地规则仍按私有材料脱敏。

agent 先用 `repo-info --repo /abs/project` 核验公开 GitHub 仓库及基线 SHA。成功后用 `prepare --public-repo --remote NAME --base SHA`，携带当前 context、计划、公开固定版本引用及本地增量；未变化的源码无需重复传递。私有或无法核验的仓库按任务需要使用本地 `--file` 材料，不能因联网失败而静默改成整仓上传。具体选择规则见 [README 的公开仓库流程](../README.md#公开仓库固定版本引用和本地增量)。

## 自主调查与材料选择

用户可以直接说“把当前改动交给上次那个复审，再检查一遍”，不用给固定格式、request ID 或文件清单。host agent 根据当前项目、上下文和任务列表找回复审，读取 diff、相关实现、调用方、测试及已有日志，整理上一轮仍待确认的问题。仅在多个实质不同的项目、目标或分支无法区分时询问。

原任务已经授权诊断、实现或测试时，host agent 可以通过正常工具运行相关且有界的测试，记录命令、源码版本、通过、失败和未运行项，再选择必要证据。Linker CLI 本身不执行项目代码；远端复审也不新增 Shell 或写仓库能力。单纯复审请求不授权代码修改、部署、破坏性命令或无关数据访问。

材料由 agent 在当前任务与 policy 范围内选择，不要求用户逐一列出文件。读取权限不等于外发授权；遇到实质性外发范围扩大、无法判断的凭据或新的高影响操作时，仍要具体说明并确认。测试输出只传与问题相关的安全摘要或已批准材料，不整份上传凭据、无关配置或日志库。

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
enabled_tools = ["review_list", "review_status", "review_result", "review_wait", "review_mark_processed"]
startup_timeout_sec = 20
# review_wait 单次最多 300 秒；tool_timeout_sec 要略大于 skill 实际传的 timeout_seconds。
tool_timeout_sec = 330
```

按[Codex 官方 MCP 文档](https://developers.openai.com/codex/mcp)注册。配置路径以实际安装/远程环境为准。全局 `--state` 必须放在 `serve-control` 前面。

本地控制 MCP 提供任务查询、报告读取和显式处理标记，不创建任务、不读取整个仓库、不联系 ChatGPT。`review_result` 和 `review_wait` 在领取远端结果时会写入私有本地缓存，`review_mark_processed` 写入本机处理记录，因此这三个工具声明为可能写入。`review_list` 和 `review_status` 不写入任务或结果；它们会查询任务绑定的交换节点。准备/发布仍走本地 CLI，以免把任意文件路径能力放进远程复审接口。

## 有必要时自主准备后续轮次

agent 读完报告后先结合代码和测试核验，优先在本地解决可直接查清的问题。只有未解决的问题足以影响方案、新测试与建议矛盾，或补齐的证据值得再次复核时，才准备追问；每轮写清具体问题和新增证据，不能例行重复原问题。

默认在同一次委派中最多追加两轮，所有分支共用这个限额。agent 在任务状态中保存起始 request ID、目标、限额和已创建的子任务 ID；准备成功即记一轮，发布重试沿用同一 ID，不因恢复会话而重置。若无法恢复剩余次数，不能自行假定还有两轮。用户明确提出的新追问可以开始新委派，但 agent 不能通过自创委派绕过限额。

这些是 skill 对 host agent 的执行规则，CLI 的 followup 本身不执行模型循环，也没有全局强制轮数限制。在原授权和剩余次数内，agent 可以自行准备并发布，之后展示提示供用户发送到 ChatGPT。用户尚未发送或当前轮仍在等待时，不批量创建猜测性的下一轮。研究回传、普通 Chat 写工具可用性和手动发送边界不变。

问题已解决、没有新的有效问题、用户停止、限额用尽或需要实质性扩大范围时结束追加复审，报告未解决项，并继续不受阻塞的已授权工作。

## 找回任务、直接读取报告和查询未处理结果

CLI 与本地控制 MCP 共用本机 state，旧任务无需迁移。先列出项目的任务，或者只列出已完成但尚未明确处理的报告：

```sh
chatgpt-linker --state "$STATE" list --project /abs/project
chatgpt-linker --state "$STATE" list --status unprocessed
chatgpt-linker --state "$STATE" result "$RID"
```

对应 MCP 调用是 `review_list({"project":"/abs/project"})`、`review_list({"status":"unprocessed"})` 和 `review_result({"request_id":"实际 ID"})`。列表包含目标、项目根目录、准备时间、状态和结果哈希，只发现当前 state 中准备的任务，不枚举整个中央交换节点。绑定远端的任务会查询原节点，失败记录在 `errors` 中；有错误不能解释为“没有待处理报告”。

列表按 request ID 排序，`cursor` 是已检查的 ID 数，`limit` 默认 20、最大 100。过滤后的空页仍可能有 `next_cursor`，应继续翻页，直到其为 null。分页期间新增任务可能改变排序位置；需要完整刷新时从 0 开始，按 request ID 去重。

`result`、`review_result` 和完成后的 `wait`、`review_wait` 除了原有路径、回执和来源漂移检查，还返回 `markdown` 正文。默认最多返回 12000 个 Unicode 字符。长报告通过 `offset` / `max_chars` 分页，响应中的 `next_offset` 为 null 才表示读到结尾。CLI 使用 `--offset` 和 `--max-chars`。每一页都检查完整报告的哈希，不能仅凭第一段或文件路径宣布已读完。

读取、等待和列出任务都不会将报告标记为已处理。agent 阅读并完成本次任务所需的报告处理后，才显式提交 `receipt.result_sha256`：

```sh
chatgpt-linker --state "$STATE" mark-processed "$RID" --result-sha256 "$RESULT_SHA"
```

MCP 对应 `review_mark_processed({"request_id":"实际 ID","result_sha256":"报告回执中的哈希"})`。重复标记同一结果保留原时间；错误哈希、报告损坏或任务取消会被拒绝。这个标记仅存于当前源机器的 state，其他机器的 agent 仍有自己的处理状态。旧任务没有标记时，其已完成结果均视为未处理。

处理记录不是实施授权，也不代表接受全部建议或完成代码修改。源码漂移仍返回 `source_check`，不能因标记完成而忽略它。ChatGPT 端仍只有 search、fetch 和 submit_review，无法列出本地项目或修改处理记录。

## 父子复审与补充材料

`followup <parent_request_id>` 从已完成且结果完整性通过检查的父任务创建下一轮。同一根任务的所有轮次共享 `conversation_id`，每一轮另有 `request_id`、`parent_request_id` 和 `round`。可从任意已完成轮次继续，也可从同一轮分支；不要将排序中的最后一个随机 ID 当作最新轮次。

```sh
chatgpt-linker --state "$STATE" followup "$PARENT_ID" \
  --goal '复核修改后的实现，重点检查新测试发现的问题' \
  --file tests/new-evidence.md --draft-stdin <<'FOLLOWUP_CONTEXT'
# Current context
## Effective task rules
这里记录当前适用的任务、文档、代码和验证约束。
## Changes and questions
这里说明相对上一轮的修改和需要继续追问的问题。
FOLLOWUP_CONTEXT
```

命令返回 prepared 子任务及其父子关系。核对范围后，使用 `publish <child_id> --approve` 发布，并将 `prompt <child_id>` 的提示交给用户。已有当前范围的授权时，也可使用 `followup ... --publish --approve`；只有 `--publish` 时仍要求 policy 的长期 auto_publish 授权。发布失败会保留子任务 ID，重试发布同一 ID。

默认的本地材料模式重新读取父任务选中的全部文件，再加入本次 `--file`；不自动扩大到整仓库。公开模式沿用已验证的公开基线 commit，并重新验证其可读性、重算当前增量，包含删除和新增；显式补充文件继续沿用。旧版本任务也可继续：缺少显式选择记录时，公开模式从原增量之外的所选文件恢复补充范围，必要时用 `--file` 明确补充。

旧材料不再合适时，可以重新选择本轮文件：

```sh
chatgpt-linker --state "$STATE" followup "$PARENT_ID" \
  --goal '检查替换后的实现' --replace-files \
  --file src/new.py --file tests/test_new.py \
  --selection-note '旧实现已删除，新实现和回归测试替代它；上一轮计划仅作为历史背景。'
```

`--replace-files` 表示本轮只使用显式列出的本地文件。若省略旧文件，必须提供 `--selection-note`；agent 负责调查并填写，用户无需记住这些参数。CLI 会冻结 omitted_files、selected_files 和说明，不根据省略自动断言文件已删除。公开模式下该选项只重选显式补充文件，当前公开增量仍完整重算。只讨论报告本身时可以不带任何 `--file`，但同样要解释为什么无需旧源码。policy、凭据扫描和大小限制仍然生效，历史报告继续保留。

上一轮 plan/question 和完整报告作为两份历史文档带入，按当前 policy 重新脱敏和扫描，并纳入文件数与总大小限制。父报告哈希指向原始已验证结果，历史文档自身的 hash 指向本轮实际冻结的脱敏文本。旧报告中的 d0001 等引用属于父轮，不能直接当成本轮引用。子轮携带当前源码；更早的祖先报告和旧源码不会递归累积，应将仍相关的决定写入当前 context。

同一个 policy 文件可以已有经用户授权的调整，但仍须指向原项目，且当前规则必须允许本轮全部材料。缺失或过时文件可在查明原因后显式重选；仍然需要的缺失材料应报告证据缺口。越界材料、扫描或大小失败会明确返回，不得放宽规则绕过。prepared、等待中、已取消或损坏的父任务不能当作完成报告继续；先恢复原任务或处理具体错误。已完成但读取授权过期的父任务仍可按原有结果领取规则继续。

`list --conversation <root_id>` 和 `review_list({"conversation_id":"根 ID"})` 查询该对话的各轮及分支，可再加 `status=unprocessed`。列表、状态和报告都返回父子关系。创建子轮不会自动标记父报告已处理，也不会把旧发布批准扩展成任意新材料的批准。

这里的 conversation 是本地复审关系，不是 ChatGPT conversation URL。用户可以在原 ChatGPT 对话发送追问，也可在新对话发送；新一轮不依赖远端读取旧任务。每一轮仍分别执行现有的冻结、发布、提交、结果校验和来源漂移检查。

## 一次任务怎样结束

`prepare` 返回 task ID；`publish` 把它变成 `waiting_for_chatgpt`。这仅表示材料可读。用户还没有发送 ChatGPT 提示时，不能说 Pro 已经在复审。

材料发布后，agent 展示完整可复制的提示词，说明在 ChatGPT 的 Chat 中启用 Deep Research，并确认 Linker 来源可用。研究阶段只读；报告完成后回到普通 Chat 提交完整 Markdown，或导出后本地导入。agent 再用 host 当前允许的 question 工具询问是否已经发送，提供「已发送，等待复审」和「稍后发送，保留任务」两个选项。异步问题必须收到实际回复才算确认。没有可用的 question 工具时，agent 以提示词和回复要求结束交接，等用户回复后接续同一个 request ID。选择稍后发送不会取消任务。

`submit_review` 成功后，完整 Markdown 和回执一起原子发布。`review_wait` 单次最多 300 秒，结果一出现立即返回；skill 默认从用户确认发送或明确要求等待时起持续轮询 90 分钟（在调用时写明「最多等 N 小时」可覆盖），开始等待后不重复向用户确认。`completed` 表示复核交接完成，agent 随即核验报告并恢复原任务；`cancelled`、`expired` 或预算用尽时报告阻塞和 request ID。CLI `wait` 等待本地或任务绑定节点上的结果，不执行项目代码；收到结果后的实现由 host agent 按原始授权推进。

```sh
chatgpt-linker --state "$STATE" wait "$RID" --timeout 5400
chatgpt-linker --state "$STATE" result "$RID"
chatgpt-linker --state "$STATE" check "$RID"
```

CLI exit codes：0 成功；2 输入/权限/策略错误；3 等待超时；4 等待任务取消/过期或 `check` 发现源文件变化；130 中断。

## Agent 已退出怎么办

之后重新启动的 agent 可以通过 `list --project /abs/project` 或 `review_list` 找回本机准备的任务，再使用 `status/result` 接手同一个 request ID。skill 不提供自动复活会话的能力；需要 host 自己实现 continuation hook。不要为了维持等待而持续发送空模型请求，更不能轮询 ChatGPT 网页。

## 结果安全与实现授权

`result` 同时返回 `artifact_path`、receipt 和 `source_check`。文件按 receipt 中的 hash 验证完整性；source check 比较**所选文件**的当前原始字节。公开模式还比较 HEAD 和增量清单的路径、状态、模式，新增改动也会使检查失败。它不检查省略文件的内容，也不重新验证公开 URL 是否仍可访问。

发现源码变化时先报告漂移，再决定重新复审或重新验证。外部 Markdown 是提案，不能扩大原始授权。原任务已经要求实现、修复或完成代码工作时，agent 应简短说明复核结论，然后在同一轮继续实现和适当测试，无需再次确认；不能把“收到报告”当成整个任务完成。明确只要规划/复核时才以交付计划结束。原始意图不明、存在实质性未决选择或需要扩大范围时，说明具体阻塞并处理，同时继续不受阻塞影响的已授权工作。

模型来源永远标记 `unverified`；这本身不阻止继续已授权工作。人工导入记录 `manual_import`。测试 fixtures 的内容不能充当真实 ChatGPT 复审。

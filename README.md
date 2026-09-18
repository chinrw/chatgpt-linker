# ChatGPT Linker

**让本地 agent 准备证据，让你在 ChatGPT 中使用 Pro 重新思考计划，再把完整 Markdown 自动交回本地 agent。**

A subscription-only, user-initiated plan-review handoff with sanitized evidence,
a constrained MCP outbox, and an explicit-invocation agent skill.

版本：**0.1.0，Alpha**。这是可运行的实现，不只是设计文档。运行时仅依赖 Python 标准库，支持 Linux/macOS/WSL2，要求 Python 3.11+。项目不包含任何 OpenAI 模型 API 后端。

> 自动化边界：你仍需在 ChatGPT 中选择所需 Pro 模型并发送一次任务提示；平台可能要求确认结果提交。程序不创建 ChatGPT 对话，不读取 Cookie，不抓取网页回答，也不能认证实际使用了哪个模型。首次必须用合成任务验证你的账号、模型和自定义工具组合。当前发布的本地测试不等于已完成真实 ChatGPT 接入。

## 正常工作流

```text
$rethink-plan
  → agent 选择材料、做语义脱敏
  → CLI 本地检查、冻结证据、发布任务
  → 你在 ChatGPT Pro 中发送生成的短提示
  → ChatGPT search / fetch，核验并重新规划
  → ChatGPT submit_review，提交完整 Markdown
  → 本地 wait / review_result 取得结果和来源漂移检查
  → agent 检查差异，再按原始授权决定下一步
```

源项目只读；服务端仅能把结果写到该任务的固定位置。**不是整个 MCP 都只读**：`submit_review` 明确是写工具。

| 接口 | 位置 | 权限 |
|---|---|---|
| `search` / `fetch` | ChatGPT 端 MCP | 读取已批准的冻结材料；无任意路径 |
| `submit_review` | ChatGPT 端 MCP | 只提交对应任务结果，无路径参数、覆盖或删除 |
| `review_status` / `review_result` / `review_wait` | 可选本地 agent MCP | 查询本地任务，不联系 ChatGPT |
| `prepare` / `publish` / `import` / `cancel` | 本地 CLI | 显式本地控制，不向 ChatGPT 暴露 |

## 安装与本地验证

在解压或克隆后的项目目录执行：

```sh
uv venv .venv
uv pip install --python .venv/bin/python .
.venv/bin/chatgpt-linker --version
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

没有 `uv` 时，等价的 `python3 -m venv` + `pip install .` 同样可用。运行时无第三方依赖；构建阶段需要 setuptools。完全离线时不需要安装：

```sh
PYTHONPATH="$PWD/src" python3 -m chatgpt_linker --help
```

不要把虚拟环境、真实 policy、任务状态或 tunnel 密钥提交到 Git。

## 第一次：用仓库内的合成示例

下面所有源文件都来自 `examples/demo`，没有真实项目数据。`--state` 是全局参数，必须放在子命令前。保存状态的位置必须在被审查项目之外。

```sh
export CHATGPT_LINKER_STATE="$HOME/.local/state/chatgpt-linker"
POLICY="$HOME/.config/chatgpt-linker/demo.toml"

chatgpt-linker init
chatgpt-linker policy-init \
  --repo "$PWD/examples/demo" \
  --output "$POLICY" \
  --allow 'PLAN.md' --allow 'demo.py'

chatgpt-linker prepare --policy "$POLICY" \
  --plan PLAN.md --file demo.py \
  --goal '检查 greeting 配置方案的兼容性、边界行为和测试覆盖'
```

记录上一步返回的真实 `request_id` 与 `bundle_sha256`，例如设置变量（不要照抄尖括号占位符）：

```sh
RID='<上一步生成的 request_id>'
SHA='<上一步生成的 bundle_sha256>'
chatgpt-linker publish "$RID" --approve
chatgpt-linker prompt "$RID"
```

`--approve` 是你对本次外发材料的批准。日常使用时，可以由你在可信 policy 中开启 `auto_publish = true`；之后 agent 在该范围内使用 `prepare --publish`。不要让 agent 自行扩大范围。

### 先测试本地回传，不假装调用了 ChatGPT

```sh
chatgpt-linker import "$RID" \
  --file "$PWD/examples/demo/REVIEW.md" --bundle-sha256 "$SHA"
chatgpt-linker wait "$RID" --timeout 0
chatgpt-linker result "$RID"
```

这是**合成、人工导入的 smoke test**，回执会记录 `manual_import`。随后准备一个**新任务**用于真实 ChatGPT 测试；已经完成的任务不可用不同内容覆盖。

## 在 ChatGPT 注册 MCP

详细步骤见 **[ChatGPT 自定义 MCP / Secure MCP Tunnel 教程](docs/CHATGPT_SETUP.zh-CN.md)**。

推荐：在本地主机运行 OpenAI 官方 `tunnel-client`，经 stdio 接入：

```sh
/absolute/path/to/.venv/bin/chatgpt-linker serve \
  --exchange /absolute/path/to/state/exchange
```

这是 MCP stdio 进程：启动后等待 JSON-RPC 输入是正常的，不会打印网页地址。不要将 CLI 的整个 state 根目录当作 `--exchange`。

官方 Tunnel 是传输方式，不是模型 API 后端。应使用清理环境的 launcher 启动 `serve`（`scripts/tunnel-launcher.example.sh` 的形状：`env -i` + 绝对路径解释器 + 空 HOME）。**本项目不提供 OS 级文件系统隔离**：launcher 只清理环境，进程读权限仍等同于你的账号；需要更强隔离请自行用沙箱运行同一条 `serve` 命令。**本项目没有公网 OAuth 服务；不要把本地调试 HTTP 端口直接暴露到互联网。**

连接后，工具清单应只有 `search`、`fetch`、`submit_review`。在 ChatGPT 中选择 Pro，发送 `prompt "$RID"` 的结果。调用成功后：

```sh
chatgpt-linker wait "$RID" --timeout 1200
```

返回的 `artifact_path` 指向固定 `review.md`，同时包含 SHA-256 回执和已选源文件的漂移检查。`wait` 只观察本地文件，不访问 ChatGPT。

## 安装 agent skill

```sh
bash scripts/install-skill.sh
```

默认安装至 `~/.agents/skills/rethink-plan`，已有同名目录时拒绝覆盖。然后在实际运行 agent 的主机上重新加载 skill，显式调用 `$rethink-plan`。

**[Agent 接力、Codex 注册与恢复教程](docs/AGENT_WORKFLOW.zh-CN.md)** 包含本地控制 MCP 配置。CLI 也能独立使用，不强制安装控制 MCP。

## 安全约束与诚实的限制

已实现：明确文件选择、内置凭据拦截、邮箱/内网 IPv4 与自定义字面替换、冻结哈希、路径/链接检查、TTL/取消、单任务固定结果、原子提交、同内容幂等、冲突拒绝、引用范围验证、私有文件权限。

**没有实现或不能保证：** 完整企业 DLP、所有商业秘密识别、多租户认证、公开 OAuth、自启动 ChatGPT、自动复活已退出的 agent、Pro 模型身份认证、整仓库一致性快照、自动删除过期数据。只检查你选中的文件；扫描器存在漏报和误报。进程级强制隔离需要按教程部署，不能仅靠提示词。

协议采用有限的 MCP stdio / 无状态 Streamable HTTP 实现，目标修订版 `2025-11-25`，非官方 SDK；没有实现 sampling、tasks、elicitation 或主动通知。参见 [架构](docs/ARCHITECTURE.zh-CN.md) 和 [测试报告](docs/TEST_REPORT.md)。

## 文档与发布

- [ChatGPT 注册和真实账号验收](docs/CHATGPT_SETUP.zh-CN.md)
- [Agent/skill 接入与恢复](docs/AGENT_WORKFLOW.zh-CN.md)
- [架构和 CLI 契约](docs/ARCHITECTURE.zh-CN.md)
- [安全模型](docs/SECURITY.zh-CN.md) · [OpenAI 条款与数据边界](docs/COMPLIANCE.zh-CN.md)
- [GitHub 仓库与发布](docs/GITHUB_PUBLISH.zh-CN.md) · [测试报告](docs/TEST_REPORT.md)

本仓库：**<https://github.com/chinrw/chatgpt-linker>（public）**，默认分支 `main`。日常更新就是普通推送：

```sh
git push origin main
```

仓库是公开的，任何进入 Git 的内容都视为公开。`state/`、真实 policy、tunnel 凭据和 `.venv` 已由 `.gitignore` 排除，但忽略规则不是加密——推送前请看一眼 `git status`。

`scripts/publish-github.sh` 是另一件事：它把源码快照发布到一个**尚不存在的、默认 private 的新仓库**，拒绝已存在的仓库，从不 force-push。它不用于本仓库的更新；命令存在也不代表远程仓库已经被创建，以脚本实际返回的 GitHub URL 为准。

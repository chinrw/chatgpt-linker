# ChatGPT Linker

**让本地 agent 准备证据，让你在 ChatGPT 中使用 Pro 重新思考计划，再把完整 Markdown 自动交回本地 agent。**

A subscription-only, user-initiated plan-review handoff with sanitized evidence,
a constrained MCP outbox, and an explicit-invocation agent skill.

版本：**0.1.0，Alpha**。这是可运行的实现，不只是设计文档。运行时仅依赖 Python 标准库，支持 Linux/macOS/WSL2，要求 Python 3.11+。项目不包含任何 OpenAI 模型 API 后端。

公开仓库增量模式还需要本机 Git 和匿名 GitHub API 的网络访问；普通本地材料模式无需这两项。

> 自动化边界：你仍需在 ChatGPT 中选择所需 Pro 模型并发送一次任务提示；平台可能要求确认结果提交。程序不创建 ChatGPT 对话，不读取 Cookie，不抓取网页回答，也不能认证实际使用了哪个模型。首次必须用合成任务验证你的账号、模型和自定义工具组合。当前发布的本地测试不等于已完成真实 ChatGPT 接入。

## 正常工作流

```text
$ultraplan
  → agent 核验仓库可见性，选择 context、计划和本地改动
  → CLI 本地检查、冻结证据、发布任务
  → 你在 ChatGPT Pro 中发送生成的短提示
  → ChatGPT search / fetch，核验并重新规划
  → ChatGPT submit_review，提交完整 Markdown
  → 本地 wait / review_result 取得结果和来源漂移检查
  → agent 核验报告，继续原任务中已授权的实现与测试
```

源项目只读；服务端仅能把结果写到该任务的固定位置。**不是整个 MCP 都只读**：`submit_review` 明确是写工具。

这里的源项目只读约束适用于材料准备和远程复核。若原始任务已经要求实现，agent 核验报告后会继续实现和测试，无需再次确认；仅规划/复核的请求仍以交付计划结束。

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

### Nix

仓库是一个 flake：`packages.default` 是 CLI，`nix flake check` 在沙箱里跑全部单元测试，`nix develop` 给 python + uv。

```sh
nix run github:chinrw/chatgpt-linker -- --version
```

Home Manager 可直接导入本仓库的模块，让 CLI 和 skill 路径随同一 flake 版本更新：

```nix
{
  imports = [ inputs.chatgpt-linker.homeManagerModules.default ];
  programs.chatgpt-linker.enable = true;
}
```

默认安装 CLI，并将 `ultraplan` 链接到 `~/.agents/skills/ultraplan` 和 `~/.claude/skills/ultraplan`。可设置 `programs.chatgpt-linker.skillTargets = [ "agents" ];` 只安装共享 skill，或设为 `[]` 只安装 CLI；`package` 可覆盖 CLI 包。模块不配置 tunnel、凭据、MCP 注册或项目发布 policy。

`skillDirectories` 可分别覆盖安装父目录，模块自动追加 `/ultraplan`。路径可以相对于 HOME，或使用 HOME 内的绝对路径；只覆盖一项不会改变另一项的默认值。例如，Claude 已配置使用自定义配置目录时：

```nix
programs.chatgpt-linker = {
  enable = true;
  skillDirectories.claude = ".config/claude/skills";
};
```

这会把 Claude 的 skill 链接放在 `~/.config/claude/skills/ultraplan`；共享目录仍为 `~/.agents/skills/ultraplan`。`skillDirectories.agents` 同样可覆盖。该选项只控制文件安装位置，不改变 agent 的目录发现配置；目标也必须在 `skillTargets` 中启用。

从手动接入迁移时，删除下游重复的 CLI package 条目、旧 `rethink-plan` / `ultraplan` 的 `home.file` 定义及自定义 skill 激活注册，统一交给此模块。更新下游锁定的 `chatgpt-linker` input 后再执行 HM switch；只更新 input 不会自动替换旧配置。模块在求值时检查 skill 的 `SKILL.md` 是否存在，避免把错误路径带到激活阶段。

Codex、Claude Code 的 MCP 注册和 tunnel-client 的 `mcp.commands` 继续使用稳定路径 `~/.nix-profile/bin/chatgpt-linker`。

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

显式调用 `$ultraplan` 已授权本次复审所需材料的准备和发布，agent 无需再要求你回复一次确认。首次缺少 policy 时，agent 可按本次范围创建 policy 并执行 `publish --approve`；长期 `auto_publish` 和已有 policy 的范围扩大仍需相应授权。

每次复核的 context 都包含 `Effective task rules`：由本地 agent 按当前 host 的优先级汇总会话、user-scope、仓库及相关子目录的有效规则，涵盖 README/文档、代码注释、commit message 和验证要求。公开仓库也携带这份摘要；不会把全局规则文件和私人配置整份上传。CLI 不会自动发现这些规则，收集与后续执行由 skill 指导 host agent 完成。

### 公开仓库：固定版本引用和本地增量

GitHub 公开仓库可以只传当前 context、计划和相对公开基线发生变化的文件，未变化的源码由复审方按固定 commit URL 阅读。CLI 使用匿名 GitHub API 核验仓库可见性和 commit 可读性，不依据 README 或远端地址猜测。

```sh
chatgpt-linker repo-info --repo /abs/project
chatgpt-linker prepare --policy ~/.config/chatgpt-linker/project.toml \
  --draft-stdin --public-repo --goal '检查当前计划与本地改动' < draft.md
```

准备后检查返回的 `public_baseline` 和 `skipped`，再发布该任务。默认基线是 HEAD 与本地缓存 upstream ref 的共同祖先；没有 upstream 时使用 `origin` 的默认分支缓存。可用 `--remote NAME --base SHA` 固定已核验的公开祖先。命令不 fetch、不修改 Git index；缓存过旧可能多传已经公开的改动。

本地增量包含未推送提交、暂存和未暂存修改、未忽略的未跟踪文件；发送的是工作树当前完整文件，删除和文件模式写入清单，重命名表示为删除加新增。清单中的 `skipped` 表示证据缺口，不能把这些路径当作公开版本未变化。Git 冲突、sparse/skip-worktree 或 assume-unchanged 状态会被拒绝，以免漏掉改动。

本地材料继续遵守 policy 和凭据扫描。`--public-repo` 不能与 `--auto` / `--glob` 混用，可追加 `--file` 补充复审方无法读取的公开文件。其他 Git 托管平台和无法核验可见性的仓库使用本地材料模式；验证失败不会自动上传整仓。公开 URL 不属于冻结包，真实 ChatGPT 会话能否读取这些 URL 仍需实测。

### 整个允许范围一次冻结

`prepare --auto` 会选入 policy 允许的全部文本文件（跳过内置黑名单、`denied_globs`、二进制、超过 200 KB 的文件和 lock 文件），`--glob 'src/*'` 可在大项目里收窄。默认上限 512 个文件 / 8 MB，policy 里 `max_files` 和 `max_bundle_bytes` 可调，硬上限 2048 / 32 MB。ChatGPT 端用 `search` 在冻结材料里找文件。

```sh
chatgpt-linker policy-init --repo /abs/project --output ~/.config/chatgpt-linker/project.toml \
  --allow '*' --deny 'tests/fixtures/*' --auto-publish
chatgpt-linker prepare --policy ~/.config/chatgpt-linker/project.toml \
  --draft-stdin --auto --glob 'src/*' --goal '...' --publish < draft.md
```

跨项目相同的敏感词放在 `~/.config/chatgpt-linker/sensitive.toml`（见 `examples/sensitive.example.toml`）。文件存在时自动合并进每个 policy，只会收紧不会放宽。

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
chatgpt-linker wait "$RID" --timeout 5400
```

返回的 `artifact_path` 指向固定 `review.md`，同时包含 SHA-256 回执和来源漂移检查。公开模式还检查 HEAD 及增量清单的变化，具体范围见[架构](docs/ARCHITECTURE.zh-CN.md#公开仓库与本地增量)。`wait` 只观察本地状态，不访问 ChatGPT。

## 安装 agent skill

```sh
bash scripts/install-skill.sh
```

默认安装至 `~/.agents/skills/ultraplan`，已有同名目录时拒绝覆盖。然后在实际运行 agent 的主机上重新加载 skill，显式调用 `$ultraplan`。旧 `rethink-plan` 安装不会自动迁移，升级步骤见[接力教程](docs/AGENT_WORKFLOW.zh-CN.md#安装位置与显式触发)。

**[Agent 接力、Codex 注册与恢复教程](docs/AGENT_WORKFLOW.zh-CN.md)** 包含本地控制 MCP 配置。CLI 也能独立使用，不强制安装控制 MCP。

## 安全约束与诚实的限制

已实现：明确文件选择、内置凭据拦截、邮箱/内网 IPv4 与自定义字面替换、冻结哈希、路径/链接检查、TTL/取消、单任务固定结果、原子提交、同内容幂等、冲突拒绝、引用范围验证、私有文件权限。

**没有实现或不能保证：** 完整企业 DLP、所有商业秘密识别、多租户认证、公开 OAuth、自启动 ChatGPT、自动复活已退出的 agent、Pro 模型身份认证、整仓库一致性快照、自动删除过期数据。内容检查仅覆盖所选材料，省略文件和外部公开源码不在冻结包内；扫描器存在漏报和误报。进程级强制隔离需要按教程部署，不能仅靠提示词。

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

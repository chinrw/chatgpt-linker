# Verification report — v0.1.0

核实日期：2026-09-17。本文件记录不同环境下的独立核实，结论分别按环境标注；无法在本机复现的环境只作为记录保留。

## A. 交付环境（Linux，CPython 3.13.5）

上一轮交付记录：88 项测试通过、`compileall` 与 `bash -n` 通过、wheel 可构建。该次运行的环境不是当前源码目录所在的机器，本机没有复现它的同一解释器版本，故此处只作为记录保留，不作为本机核实结果。

## B. 发布前复核（macOS arm64，CPython 3.14.7）

在提交到 GitHub 之前，对当前源码目录重新完整执行：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
# Ran 88 tests — OK

python3 -m compileall -q src tests scripts
bash -n scripts/*.sh

uv build --wheel --out-dir <tmp>            # 隔离构建，不经 pip
uv venv <tmp> && uv pip install --no-index <built wheel>
```

wheel 安装到**全新虚拟环境**后，用安装出的 console script（不使用源码 PYTHONPATH）执行：

```text
plan-review --version → 0.1.0
init → policy-init → prepare → publish → prompt
import（合成人工回执）→ wait → result        回执 source=manual_import
```

同一次还用一个**合成 MCP 客户端**通过真实 stdio 子进程验证远程面：

```text
initialize → plan-review-bridge 0.1.0，协议 2025-11-25
tools/list → 仅 fetch / search / submit_review；submit_review 无 path 参数
fetch <request_id>:request、search、fetch 传绝对路径 → 被拒绝
submit_review → completed，回执 source=mcp_submit
本地 wait → artifact_path 指向固定 review.md，source_check.unchanged=true
```

这是**合成客户端与合成材料**，不代表真实 ChatGPT 会话。运行测试不需要网络、真实账号、模型 API 或第三方运行时包。

### 本机首次执行时的失败（已修复）

初次执行是 86/88：`test_scripts.py` 两项失败，原因是发布白名单要求存在 `.github/`，而工作副本缺少 `.github/workflows/ci.yml`。同一份工作副本里 `.gitignore` 也不存在——白名单对缺失的**根文件**是静默跳过，所以只有目录缺失会报错。补齐后 88/88 通过。这正是 `snapshot_source.py` 失败即停设计要暴露的问题：缺失的发布目录不会被静默跳过。

### 88 项测试的分布

| 测试文件 | 数量 | 重点 |
|---|---:|---|
| test_sanitize.py | 23 | 已知凭据、语义替换、最终出口、路径/链接、权限、大小/类型 |
| test_store.py | 28 | 显式授权、不可变快照、来源漂移、隔离、提交、并发、取消/过期 |
| test_protocol.py | 17 | JSON-RPC、工具权限、参数验证、资源、真实 stdio 子进程、控制面 |
| test_http.py | 6 | 实际 loopback HTTP、鉴权/Host/Origin、格式限制、通知无写入 |
| test_cli.py | 7 | 实际 CLI 子进程、人工导入、等待恢复、错误安全、源目录保护 |
| test_scripts.py | 7 | skill 安装、源码快照、模拟 gh 的权限/冲突/发布路径 |
| **合计** | **88** | 单元与本地集成回归 |

额外安装验证：把生成的 wheel 安装到**新建的虚拟环境**，不使用源码目录的 PYTHONPATH。通过安装后的 console script 执行 policy-init、prepare/publish；通过真实 MCP stdio 初始化、fetch、submit_review；再由 wait 取得 Markdown。确认结果完整、hash 校验通过、所选源文件未改变。

源码归档会从白名单生成，排除 `.venv`、缓存、真实状态和 Git history；文档中的相对链接已检查，无断链。GitHub 发布脚本的测试使用明确的模拟 gh，**没有实际创建远程仓库**；本仓库是用普通 `git push` 推送到既有的 `chinrw/codex-linker`，没有经过该脚本。

可选 coverage 测量：父进程 74% statement coverage。CLI 多数测试运行于独立子进程，这次未合并其 coverage，因此该数字不代表 CLI 未测试，也不应被改写成一个不存在的全进程覆盖率。

## 回归中发现并修复

- 非 ASCII HTTP Authorization 不再导致异常，安全返回 401。
- 非法 JSON-RPC request ID 不会作为有效 ID 反射回响应。
- 错误地把 state 放进源项目时，prepare 在创建任何 state 目录之前拒绝。
- 自定义脱敏替换后的文本再次做字符/行长度检查。
- policy 必须由运行用户拥有，且不可被其他用户写入。

## GitHub 发布

- 仓库：<https://github.com/chinrw/codex-linker>（**public**，仓库所有者手工创建，不是由发布脚本创建）
- 首次提交：`57441604974e0a23fce3d861779ed48b4751f40e`，46 个文件：源码、测试、文档、skill、示例、脚本、CI 配置；不含任务 state、`.venv`、缓存或凭据
- 推送方式：普通 `git push origin main`；每次推送后用 `git ls-remote origin` 核对远端 `refs/heads/main` 与本地 `main` 的 SHA 一致，`gh repo view` 显示 `defaultBranchRef.name=main`、`isEmpty=false`
- 记录性提交会改变 head，所以这里不把“当前 head”写成固定值；以 `git ls-remote origin` 与 Actions 页面为准
- `scripts/publish-github.sh` 只在模拟 `gh` 下测试过，本次**没有**真实调用它；它面向的是另建一个不存在的私有仓库

### 远端 CI

| 运行 | head | 结果 |
|---|---|---|
| [run 35206621575](https://github.com/chinrw/codex-linker/actions/runs/35206621575) | `5744160` | 5 个 job 全部 `success` |
| [run 35206837850](https://github.com/chinrw/codex-linker/actions/runs/35206837850) | `f1a4a96` | 5 个 job 全部 `success`，无 annotation |

两次都是同一矩阵：ubuntu-latest 上的 Python 3.11 / 3.12 / 3.13，以及 macos-latest 上的 Python 3.12 / 3.13。每个 job 执行 compileall、`bash -n scripts/*.sh`、88 项 unittest，并用 uv 构建 wheel。

第一次运行留下两条非失败类 annotation（Node 20 弃用提示、uv 缓存无法失效）；第二次运行前已升级到 `actions/checkout@v7`、`actions/setup-python@v7`、`astral-sh/setup-uv@v10.1.0` 并关闭无意义的 uv 缓存，annotation 归零。CI 结论只对表中这两次运行负责；它验证的是**测试与构建**，不验证真实 ChatGPT 会话。此后每次推送到 `main` 都会重跑同一矩阵，本文件不再逐次登记。

## 未执行／不得据此宣称已通过

- 用户的 ChatGPT Pro 模型与自定义 MCP 写工具的真实账号验收。
- OpenAI Secure MCP Tunnel 的实际认证、组织关联、运行及连接。
- 官方 MCP SDK/Inspector 或其他独立客户端的完整互操作性认证。
- Python 3.11/3.12 在**本机**的执行：本机只有 CPython 3.14.7。这两个版本只在 GitHub Actions 的 ubuntu/macOS runner 上执行过（见上表），不是本地运行。
- Windows 原生执行；本项目定位 POSIX（Linux/macOS/WSL2），未测试 Windows。
- 完整企业 DLP、渗透测试、形式化证明或零泄露保证。

定位：可运行的 Alpha 实现。先按 ChatGPT 接入教程用合成材料验证实际账号，再批准真实项目外发。

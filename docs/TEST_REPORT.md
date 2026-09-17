# Verification report — v0.1.0

核实日期：2026-09-17。本文件记录两次独立核实，环境不同，结论分别标注。

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

初次执行是 86/88：`test_scripts.py` 两项失败，原因是发布白名单要求存在 `.github/`，而工作副本缺少 `.github/workflows/ci.yml`、`.gitignore`、`.dockerignore`。补齐这三个发布文件后 88/88 通过。这正是 `snapshot_source.py` 的失败即停设计要暴露的问题——缺失的发布文件不会被静默跳过。

| 测试文件 | 数量 | 重点 |
|---|---:|---|
| test_sanitize.py | 23 | 已知凭据、语义替换、最终出口、路径/链接、权限、大小/类型 |
| test_store.py | 28 | 显式授权、不可变快照、来源漂移、隔离、提交、并发、取消/过期 |
| test_protocol.py | 17 | JSON-RPC、工具权限、参数验证、资源、真实 stdio 子进程、控制面 |
| test_http.py | 6 | 实际 loopback HTTP、鉴权/Host/Origin、格式限制、通知无写入 |
| test_cli.py | 7 | 实际 CLI 子进程、人工导入、等待恢复、错误安全、源目录保护 |
| test_scripts.py | 7 | skill 安装、源码快照、模拟 gh 的权限/冲突/发布路径 |
| **合计** | **88** | 单元与本地集成回归 |

额外安装验证：把生成的 wheel 离线安装到**新建的虚拟环境**，不使用源码目录的 PYTHONPATH。通过安装后的 console script 执行 policy-init、prepare/publish；通过真实 MCP stdio 初始化、fetch、submit_review；再由 wait 取得 Markdown。确认结果完整、hash 校验通过、所选源文件未改变。

源码归档会从白名单生成，排除 `.venv`、缓存、真实状态和 Git history；文档中的相对链接已检查，无断链。GitHub 发布脚本的测试使用明确的模拟 gh，**没有实际创建远程仓库**。

可选 coverage 测量：父进程 74% statement coverage。CLI 多数测试运行于独立子进程，这次未合并其 coverage，因此该数字不代表 CLI 未测试，也不应被改写成一个不存在的全进程覆盖率。

## 回归中发现并修复

- 非 ASCII HTTP Authorization 不再导致异常，安全返回 401。
- 非法 JSON-RPC request ID 不会作为有效 ID 反射回响应。
- 错误地把 state 放进源项目时，prepare 在创建任何 state 目录之前拒绝。
- 自定义脱敏替换后的文本再次做字符/行长度检查。
- policy 必须由运行用户拥有，且不可被其他用户写入。

## 未执行／不得据此宣称已通过

- 用户的 ChatGPT Pro 模型与自定义 MCP 写工具的真实账号验收。
- OpenAI Secure MCP Tunnel 的实际认证、组织关联、运行及连接。
- 官方 MCP SDK/Inspector 或其他独立客户端的完整互操作性认证。
- Docker 镜像构建与容器挂载运行。
- macOS、Python 3.11/3.12 的本地执行；已提供相应 GitHub Actions 矩阵，尚未在远端运行。
- GitHub 仓库创建、远端 push 或 GitHub Actions 成功结果。
- 完整企业 DLP、渗透测试、形式化证明或零泄露保证。

定位：可运行的 Alpha 实现。先按 ChatGPT 接入教程用合成材料验证实际账号，再批准真实项目外发。

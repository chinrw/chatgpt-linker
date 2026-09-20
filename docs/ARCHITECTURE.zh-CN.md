# 架构、状态与接口

## 实现范围

这是一个单用户、私有连接的 Python 程序。无需模型 API，也没有常驻模型调度器。进程分为本地 CLI、远程证据 MCP，以及可选本地控制 MCP；复用同一存储层。

flake 导出 `homeManagerModules.default`（同 `homeManagerModules.chatgpt-linker`）。模块位于 `nix/home-manager.nix`，通过 `programs.chatgpt-linker.enable` 安装 CLI，并按 `skillTargets` 声明共享 agent / Claude 的 skill 链接。默认两处都启用；空列表只安装 CLI。它只负责安装，不创建任务、发布授权、凭据或 tunnel 服务。使用方移除旧 skill 激活注册后，链接随 HM generation 更新。

```text
src/chatgpt_linker/
  fs.py            openat/no-follow、私有权限、原子写入和文件锁
  sanitize.py      可信 TOML policy、材料过滤和本地脱敏
  git_evidence.py  匿名 GitHub 基线验证、只读 Git 增量与公开引用
  store.py         冻结包、授权、引用、固定结果、状态与来源漂移
  protocol.py      有限 MCP/JSON-RPC，stdio 与工具路由
  http_server.py   loopback-only 调试用无状态 Streamable HTTP
  cli.py           用户和本地 agent 的控制入口
```

## 存储布局

```text
state/                            0700；不在被审查项目中
  private/<request_id>/           不提供给远程 MCP
    candidate.json               已扫描的候选包，不是原始秘密副本
    provenance.json              本地项目路径、策略 hash、所选原始文件 hash
  exchange/
    inbox/<request_id>/
      bundle.json                不可变脱敏文本及确定性 hash
      grant.json                 TTL、撤销状态、是否允许 submit
    outbox/<request_id>/
      .lock                      并发 submit/cancel 的 flock
      result/                    单次原子目录发布
        review.md
        receipt.json
```

目录 0700、文件 0600；state 的祖先目录和运行账户必须可信。不是防御同一 UID 恶意进程或 root 的沙箱。

远程进程接收 `--exchange`，不接收源仓库/策略路径。在更强部署中以只读方式挂载 exchange，再单独开放 outbox 写权限。

## 生命周期

```text
prepare → prepared
publish → waiting_for_chatgpt
submit_review / import → completed
cancel → cancelled
TTL 到期且尚未完成 → expired
```

`prepare` 失败不会公开任何任务；`--publish` 因缺少授权失败时，保留 prepared ID，避免重做任务。发布后不能替换材料。取消针对已发布任务；prepared 草稿当前没有远程权限。

已完成结果在本地可于 TTL 到期后领取，但远程证据读取/再次提交都会被拒绝。取消优先于完成状态；取消后的结果不会被 `result` 自动领取。TTL/取消是访问撤销，**不是物理擦除**。v0.1 没有自动数据清理器。

## Bundle 完整性

先捕获并扫描明确选择的文本，再检测所选文件在捕获期间是否变化。发布的始终是原先扫描过的字节，不会重新读取活动工作树作为外发内容。

Canonical JSON 使用 UTF-8、key 排序、紧凑分隔符及有限数字；bundle SHA-256 不包含自身。每份文档另有内容 hash，访问时验证。检查结果会在同内容重复提交时再次验证存储完整性。

CRLF/CR 统一为 LF；显示路径可以脱敏，因此源行号是冻结文本的逻辑行号。普通本地材料模式不提供 Git commit attestation。

### 公开仓库与本地增量

`repo-info --repo PATH [--remote NAME] [--base REF]` 只检查 Git 和匿名 GitHub API，不创建任务或 state。支持标准 github.com HTTPS/SSH remote；验证仓库 `private=false`、`visibility=public`、仓库身份一致，以及基线 commit 可匿名读取。采用 GitHub 的 [repository](https://docs.github.com/en/rest/repos/repos#get-a-repository) 和 [Git commit](https://docs.github.com/en/rest/git/commits#get-a-commit-object) 接口，不加载 GitHub token，拒绝重定向。私有、未知、限流或网络失败统一报告 `PUBLIC_REPO_UNVERIFIED`，不能据此断言仓库私有。

`prepare --public-repo` 重做验证，冻结一份 `public_baseline` 文档及本地改动文件。默认选择 upstream remote；没有时用 origin。基线为 HEAD 与该远端缓存 ref 的共同祖先；`--base` 可显式指定公开祖先。不会 fetch，缓存陈旧可能多传已公开文件。无可用 ref、本地缺少 commit 或基线不属于 HEAD 的祖先时报错，不能猜测基线。

增量相对固定基线计算，覆盖未推送提交和最终工作树；Git index 不作为独立版本传递。非忽略 untracked 文件参与选择。普通文件发送完整内容；删除以清单记录；重命名拆成删除/新增；可执行位写入 Git mode。policy 排除、敏感内容、二进制、超限文件、符号链接和 submodule 作为 `skipped` 写入证据缺口清单。冲突、sparse/skip-worktree、assume-unchanged 状态拒绝准备。公开模式不支持 `--auto` / `--glob`，仍可用 `--file` 增补明确文件。

本地 provenance 另存 HEAD、基线和增量清单。捕获结束、publish 和 result 检查所选文件内容及 HEAD/增量清单漂移。公开 URL 的可用性和省略文件内容不在此检查内。基线链接固定 commit，但公开文件字节不在 bundle 中；这不是整仓快照。Git 只读命令禁用可选 index 写入、fsmonitor、外部 diff、textconv 和 clean/process filters，不运行项目代码。

## 远程工具

- `search(query, cursor=0)`：query 必须以真实 request ID 开头，其后为按空白分隔的字面查询词（AND）。每页最多 20 项。返回 next_cursor，不是自然语言语义检索。
- `fetch(id, start_line=1, max_lines=200)`：id 为 `<request_id>:request` 或返回的 `d0001` 等文档 ID。最多 500 行且 24 KB/响应；返回 next_start_line 和 bundle hash。
- `submit_review(request_id, bundle_sha256, markdown)`：无 path/URL 参数，只保存对应任务结果。只接受完整 Markdown（100–256000 UTF-8 bytes）。

结果必须包含六个二级标题：`Summary`、`Evidence`、`Plan`、`Validation`、`Risks`、`Open Questions`，正文语言自由。引用形如 `[d0001:L1-L3]`；至少一个有效引用，所有匹配该格式的引用均须在范围内。

引用检查只验证文档/行范围存在，不验证论证正确性或引用完整性，也不保证模型没有遗漏信息。公开模式允许另附固定 commit 的 blob URL / 行锚点；这些外部引用不由服务端校验，仍要求至少一个有效本地文档引用（例如 context 或计划）。复审方无法读取公开代码时必须报告缺口；用新任务补充所需 `--file` 材料。

`search/fetch` 是只读；`submit_review` 是非破坏性的写入。已成功提交后，相同字节返回原回执，不同字节报 `RESULT_CONFLICT`。更新计划请新建任务；没有 overwrite、append 或 delete 工具。

每个连接可通过 `serve --request <id>` 缩小至一个任务。默认该私有连接能访问**这个用户已经发布的任务**，没有会话身份到任务的多租户 ACL。随机 request ID 不是鉴权密钥；不要分享连接或允许多个用户共用。

## MCP 协议范围

有限实现目标：[MCP 2025-11-25 transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) 与 [tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。不是官方 SDK，也不宣称完整实现规范。

支持 initialize/ping、tools list/call、真实 `planreview://` 资源读取，以及 stdio newline JSON-RPC。工具返回等值 JSON 文本和 structuredContent。拒绝重复 JSON key、NaN、JSON-RPC batch、未知工具、未知参数、非法 Unicode 和过大消息。

可以协商列出的旧修订版；不提供 tasks、sampling、roots、elicitation、prompts、资源订阅或主动服务端推送。`planreview://` 是本服务实现的 MCP URI，**不是能从普通浏览器打开的公开网页**。

HTTP 是无状态 JSON 响应模式：POST /mcp，通知返回 202；GET/DELETE 返回 405，不创建会话和 SSE 长连接。只绑定 127.0.0.1，校验 bearer、Host、Origin、协议、长度和内容类型，限制并发数。此接口没有公网 OAuth，不作为直接面向 ChatGPT 云端的公开服务。

## 本地 HTTP 调试

```sh
chatgpt-linker http-token --output "$HOME/.config/chatgpt-linker/http-token"
chatgpt-linker serve --exchange "$HOME/.local/state/chatgpt-linker/exchange" \
  --transport http --port 8766 \
  --token-file "$HOME/.config/chatgpt-linker/http-token"
```

本地客户端必须提供 `Authorization: Bearer <本地 token>`、JSON Content-Type，以及同时接受 application/json 与 text/event-stream。token 不放 URL 或日志。正式 ChatGPT 接入优先使用官方 Tunnel 的 stdio。

## 不存在的能力

没有主动调用 ChatGPT Pro、模型 API fallback、网页自动化、shell 工具、自动代码实施、任意路径工具、后台会话复活、完整项目同步、多用户 OAuth。后续扩展必须保留这些权限边界，不用新的功能名称掩盖写入或扩大外发范围。

# ChatGPT 自定义 MCP 注册教程

核实日期：2026-09-17。这里配置的是私人 developer-mode app，不是向公开目录提交插件。本实现仅支持单用户私有连接。

## 0. 先明确两种凭据

本项目不读取 OpenAI 模型 API key，不调用 Responses/Chat Completions。你在 ChatGPT 中手动选择 Pro，使用相应产品额度。

官方 Secure MCP Tunnel 仍要求 **tunnel runtime key** 和 `tunnel_id`。它们用于传输认证，不会使这套程序变成模型 API 调用。不能把“使用 Pro 订阅”理解成“不需要任何传输认证”。实际平台资格、权限和收费政策以账号为准，本项目不作额外费用保证。[1]

不要把 runtime key 放进复审文件、仓库、skill、提示词或聊天。MCP 子进程不需要继承它。

## 1. 本机准备

完成 README 的安装、`init`、合成任务 `prepare` / `publish`。确认：

```sh
chatgpt-linker doctor
chatgpt-linker status '<真实 request_id>'
```

状态应为 `waiting_for_chatgpt`。`doctor` 只检查本地情况，不会宣称已经连上 ChatGPT。

创建一个空的私有 HOME，然后复制 launcher 到仓库外：

```sh
mkdir -p "$HOME/.config/chatgpt-linker/empty-home"
chmod 700 "$HOME/.config/chatgpt-linker" "$HOME/.config/chatgpt-linker/empty-home"
cp scripts/tunnel-launcher.example.sh "$HOME/.config/chatgpt-linker/tunnel-launcher.sh"
chmod 700 "$HOME/.config/chatgpt-linker/tunnel-launcher.sh"
```

编辑 launcher 的三个固定绝对路径：

```text
PYTHON_BIN = 安装本项目的 .venv/bin/python
EXCHANGE   = 状态目录下的 exchange，不是项目目录，也不是整个 state
SAFE_HOME  = 刚创建的 empty-home
```

launcher 使用 `env -i` 清空环境；Tunnel 父进程持有 runtime key，MCP 子进程只收到必要的 PATH/HOME。直接运行 launcher 会等待 stdio 消息，不是卡死。

## 2. 建立 OpenAI Tunnel

在官方 [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels) 创建 tunnel。记录它实际生成的 `tunnel_id`，关联管理它的 Platform organization 和**实际创建 ChatGPT app 的 workspace**。

创建/修改需要 Tunnels 的 Read + Manage；运行/选择需要 Read + Use。只有 Pro 订阅名称不足以证明账号拥有这些权限。缺权限时按页面提示配置权限，不通过本项目绕过。[1]

从官方 Platform 页面或 [openai/tunnel-client](https://github.com/openai/tunnel-client) 获取适合平台的当前客户端并验证发行来源。先运行：

```sh
tunnel-client help quickstart
```

通过你本机的安全方式把 runtime key 提供给 `CONTROL_PLANE_API_KEY`，不要把真实值写进命令历史或脚本。然后根据官方 quickstart 初始化 stdio profile；替换实际 ID 和 launcher 路径：

```sh
tunnel-client init --sample sample_mcp_stdio_local \
  --profile chatgpt-linker \
  --tunnel-id '<真实 tunnel_id>' \
  --mcp-command '/absolute/path/to/tunnel-launcher.sh'

tunnel-client doctor --profile chatgpt-linker --explain
tunnel-client run --profile chatgpt-linker
```

Tunnel 客户端需要访问 OpenAI 的出站 HTTPS；不需要给这台开发机开放公网入站端口。它必须保持运行，工具发现与调用才能完成。[1]

> 以上外部工具步骤按官方文档编写，本交付环境没有运行 `tunnel-client` 或登录你的 ChatGPT。请把这里当作待在真实主机执行的接入过程，而不是已部署报告。

## 3. 在 ChatGPT 网页创建连接

按当前官方教程：Settings → Security and login → Developer mode。随后在 Plugins 页面点击加号创建 developer-mode app，Connection 选择 **Tunnel**，选中刚创建的 tunnel 或填写其 ID。[2]

名称建议 `ChatGPT Linker`。完成后检查发现的工具及权限：

```text
search          readOnlyHint = true
fetch           readOnlyHint = true
submit_review   readOnlyHint = false
```

不要注册本地 `serve-control` 作为这个远程 app。它会暴露本地结果路径，不是给复审模型的证据服务。

新建对话，确认实际可选择所需 Pro 模型以及这个 app。修改工具 schema 后 Refresh 连接，再新建对话测试。平台可能弹出写入确认；只使用平台提供的正式批准机制，不把 submit 伪装成只读来隐藏确认。[2][3]

## 4. 必须执行的真实账号验收

准备一份**新的合成任务**，执行 `chatgpt-linker prompt <id>`，把生成的短提示发送到刚建立的 ChatGPT Pro 会话。

验收顺序：

1. `fetch` 读到正确 request 和证据，bundle hash 一致。
2. 模型输出完整计划，并调用 `submit_review`，而不只是发聊天回答。
3. 你批准必要的写入操作。
4. 工具返回成功回执；本地 `wait <id> --timeout 0` 返回 exit 0 和真实结果路径。
5. 打开文件确认内容完整，再检查 `source_check.unchanged`。

服务端回执 `model_attestation = unverified` 是有意设计。MCP 无法独立证明所选 ChatGPT 型号，也不能代你切换到 Pro。

## 5. 写工具不可用时

不同账号、工作区政策或模型组合的可用性必须以实际测试为准。[2][3]

两种降级均已实现：启动时加 `serve --read-only` 隐藏写工具；或发布任务时用 `publish <id> --approve --read-only` 撤去该任务的远程提交权限。两者都不会把结果藏进读工具参数。

让 ChatGPT 输出同一份 Markdown，然后保存到你选择的本地文件：

```sh
chatgpt-linker import '<request_id>' --file /absolute/path/to/review.md \
  --bundle-sha256 '<该任务的原始 bundle_sha256>'
```

后续验证、固定结果存储和 agent 领取照常工作。仍只使用 ChatGPT 订阅，不暗中换成 API。

## 6. 运行面与隔离边界

`serve` 是 tunnel-client 在**你本机、以你的账号**拉起的进程。推荐用仓库外固定路径的 launcher 启动它（形状见 `scripts/tunnel-launcher.example.sh`）：`env -i` + 绝对路径的解释器 + 一个空的 `SAFE_HOME`。这样它不继承你的凭据环境变量，对外接口也只有 `search` / `fetch` / `submit_review`。

**本项目不提供操作系统级文件系统隔离。** launcher 只清理环境，进程的读权限仍等同于你的账号；`fetch` 只接受 `<request_id>:request` 这类 ID，约束的是协议接口，不是进程权限。不要因此把“已经脱敏”理解成“即使进程被滥用也没有影响”。

需要更强隔离时，请用你自己的沙箱运行**同一条**命令：

```sh
exec <你的沙箱> -- /absolute/path/to/.venv/bin/chatgpt-linker serve --exchange <EXCHANGE>
```

只把 exchange 挂进去；源仓库、private provenance、HOME、SSH agent、云凭据和 Docker socket 都不要挂。UID 与目录权限（exchange 需属于运行 UID 且 mode 0700，否则 `UNSAFE_STATE`）必须自行验证——**本项目不附带容器配方，也不对任何第三方沙箱配置的正确性负责**。

无论哪种方式，Tunnel 的网络访问都留在宿主父进程；stdio 子进程不需要网络。

## 7. 常见问题

| 现象 | 检查 |
|---|---|
| Tunnel 不在 ChatGPT 列表 | 是否关联了正确 ChatGPT workspace；是否有 Read + Use |
| MCP 一直等待 | stdio 本来就等待 JSON-RPC；使用 tunnel-client doctor 或 Inspector |
| `UNSAFE_STATE` | exchange、inbox/outbox、任务目录需属于运行 UID，mode 0700；文件 mode 0600 |
| `STATE_MISSING` | 是否把 `--exchange` 错指向整个 state；任务是否尚未发布 |
| `UNAVAILABLE` | 任务是否取消/过期；服务是否使用 `--request` 固定为另一个任务 |
| `MISSING_SECTIONS` | 保留六个 `##` 英文机器标题；正文可用中文 |
| `INVALID_EVIDENCE` | 引用必须指向当前包的实际文档 ID 和行范围 |
| `RESULT_CONFLICT` | 结果不可修改；准备新任务做下一轮复审 |
| `wait` exit 3 | 本地等待超时，保留原 ID 恢复；不等于 ChatGPT 已失败 |

调试可用官方 [MCP Inspector](https://github.com/modelcontextprotocol/inspector)，对 stdio launcher 运行协议检查。它不证明 ChatGPT Pro 账号兼容性。

## 官方来源

[1] [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。
[2] [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)。
[3] [ChatGPT Developer mode](https://developers.openai.com/api/docs/guides/developer-mode)。

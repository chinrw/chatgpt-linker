# 多台机器共用一个交换节点

项目可以留在各自的源机器上，由一个常开的交换节点保存复审材料和结果。源机器需要安装同版本的 Linker CLI；交换节点需要已有的 ChatGPT tunnel 连接，以及源机器能够访问的 HTTPS 地址。仍需由你在 ChatGPT 中发送一次生成的任务提示。

材料选择、脱敏、发布授权和源码漂移检查都在源机器完成。上传只包含冻结文本、哈希、TTL 和是否允许提交结果；原始仓库路径、policy 和本地来源记录保留在源机器。交换节点与现有 ChatGPT MCP 共用 `exchange` 目录。

## 配置交换节点

在交换节点上初始化状态，并生成独立的交换访问令牌：

```sh
chatgpt-linker init
chatgpt-linker http-token --output "$HOME/.config/chatgpt-linker/exchange-token"
```

交换令牌与 tunnel API key 是两种凭据。第一版供同一用户的可信机器使用，这些机器共享交换令牌。持有它的客户端可以上传任务、读取已知任务的结果、取消任务或手工导入结果；没有按机器划分的任务权限，也没有任务列表接口。request ID 不能代替令牌。

直接在 LAN 监听时需要 TLS 证书。可以使用已有证书；下面用 OpenSSL 生成一个示例自签名证书。将 `NODE_IP` 换成交换节点的固定 LAN IPv4 地址。证书中的地址必须与客户端连接的地址一致。

```sh
umask 077
NODE_IP='192.168.1.10'
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -subj '/CN=chatgpt-linker-exchange' \
  -addext "subjectAltName=IP:$NODE_IP" \
  -keyout "$HOME/.config/chatgpt-linker/exchange-key.pem" \
  -out "$HOME/.config/chatgpt-linker/exchange-cert.pem"

chatgpt-linker serve-exchange \
  --exchange "$HOME/.local/state/chatgpt-linker/exchange" \
  --listen "$NODE_IP" --port 8767 \
  --token-file "$HOME/.config/chatgpt-linker/exchange-token" \
  --tls-cert "$HOME/.config/chatgpt-linker/exchange-cert.pem" \
  --tls-key "$HOME/.config/chatgpt-linker/exchange-key.pem"
```

入口给 TLS 握手、请求行和完整请求头共用 15 秒的总时限，持续发送少量字节不会延长它。请求头解析完成后，正文上传和响应保持原有的 15 秒空闲超时。

这是前台进程，退出会停止交换入口。在节点防火墙中仅允许需要的 LAN 来源访问该端口。`--exchange` 必须与 tunnel 使用的目录一致；自定义 `--state` 时需要相应调整。

如果已有 HTTPS 反向代理，可以省略 `--listen` 和两个 TLS 参数，让后端只监听 `127.0.0.1:8767`。用 `--allow-host linker.example.internal` 指定代理转发的准确 Host；非默认端口要包含端口。代理应保留 Authorization，限制上传大小不超过 48 MiB，并且只向选定内网开放。直接监听 `0.0.0.0` 时必须提供 TLS 和明确的 `--allow-host`，不能使用通配 Host。

## 配置源机器

通过已有的安全通道把交换令牌及证书的公开部分交给源机器。令牌文件必须由当前用户持有，权限为 `0600`。交换节点的 TLS 私钥和 tunnel API key 留在节点上。

```sh
export CHATGPT_LINKER_EXCHANGE_URL='https://192.168.1.10:8767'
export CHATGPT_LINKER_EXCHANGE_TOKEN_FILE="$HOME/.config/chatgpt-linker/exchange-token"
export CHATGPT_LINKER_EXCHANGE_CA_FILE="$HOME/.config/chatgpt-linker/exchange-cert.pem"
```

受系统信任的证书无需设置 `CHATGPT_LINKER_EXCHANGE_CA_FILE`。等价的 CLI 全局参数为 `--exchange-url`、`--exchange-token-file` 和 `--exchange-ca-file`，放在子命令之前。客户端始终验证证书及主机名，不跟随重定向，也不使用环境中的 HTTP 代理。

接着按普通单机流程在源机器准备和发布任务，例如：

```sh
chatgpt-linker prepare --policy "$HOME/.config/chatgpt-linker/project.toml" \
  --plan PLAN.md --file src/example.py --goal '复核当前计划'

RID='<prepare 返回的 request_id>'
chatgpt-linker publish "$RID" --approve
chatgpt-linker prompt "$RID"
```

已有 policy 授权 `auto_publish` 时，`prepare --publish` 也会使用配置的交换节点。网络配置本身不授权发布材料。

## 领取或恢复任务

在 ChatGPT 中选择**交换节点**对应的 Linker 连接，发送 `prompt` 输出的提示。发送后回到源机器等待：

```sh
chatgpt-linker wait "$RID" --timeout 5400
chatgpt-linker result "$RID"
```

返回的 `artifact_path` 是源机器上的 Markdown 文件，可以直接交给本地 agent。原始回执会保留；`source_check` 检查源机器工作树中的变化。`status`、`cancel`、本地控制 MCP 和手工 `import` 同样跟随该任务保存的交换节点。手工导入的回执仍标记 `manual_import`。

首次发送前，源机器把节点地址以及令牌、CA 文件的本地路径保存在私有状态里。后续命令无需重复传连接参数，凭据文件应保留。连接超时不等于提交失败：用同一 request ID 在同一节点查询或重新发布，相同材料重试不会替换内容、延长 TTL 或恢复已取消的任务。首次请求完全未到达时，查询可能返回 `STATE_MISSING`；重新发布同一任务即可。不会自动切换节点或改成本地任务。

令牌可在原路径替换后重试。要改变节点地址，需要新建任务；已发布的单机任务也不能直接迁移为远端任务。源码或 policy 已变化时，仍需遵守普通流程的重新准备要求。

节点地址按主机名和有效端口比较：主机名大小写、HTTPS 的省略端口与 `:443`、HTTP 的省略端口与 `:80` 都视为等价。旧任务保存的地址会在读取时规范化，无需迁移状态文件；不同主机、协议或非默认端口仍视为不同节点。

## 单机用法和限制

不设置交换连接参数的新任务仍使用本地 `exchange`，原有 stdio MCP 和本地调试 HTTP 用法保持不变。已绑定远端的任务继续使用保存的节点。

LAN 入口只接收任务和结果操作，不提供 shell、任意文件读取或 ChatGPT 启动能力。客户端只允许向 loopback 使用明文 HTTP；其他地址需要 HTTPS。Tailscale 可作为到相同 HTTPS 入口的网络路径使用，无需 Linker 专用集成。

交换节点停止时，远端任务的发布、查询和领取会失败；源机器不会用缓存冒充当前状态。已经完成的结果在 TTL 到期后仍能领取，取消则阻止后续领取。TTL 与取消都不会自动删除文件。

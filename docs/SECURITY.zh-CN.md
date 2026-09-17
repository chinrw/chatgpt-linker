# 安全模型

## 可信边界

本程序用于一个用户、一个私有连接。安装的代码、用户批准的仓库外 policy、状态目录的祖先目录，以及运行账户可信。它不是多租户服务，也不防御同 UID 恶意进程、root、恶意 Python 安装或主机被攻破。

源项目、旧 plan、注释、AGENTS.md、外部复审结果都作为数据看待。它们没有权力扩大文件 allowlist、改变授权、选择新模型后端或发出执行命令。

## 防泄露流水线

显式选择路径 → 检查文件类别和 allowlist → 不跟随链接的有限读取 → UTF-8/大小检查 → 凭据扫描 → 用户字面替换和邮箱/内网 IPv4 脱敏 → 再扫描 → 冻结 hash → 用户批准发布。

所有 selected files、goal、draft、文档显示路径和最终发布 JSON 都检查。删除 diff 行也不是例外。不会遍历 Git 历史、自动执行 git 配置/钩子、构建脚本、测试或凭据校验网络请求。

扫描器针对常见凭据模式，是确定性后备，不是完整 DLP。它不联网验证 token，不证明所有个人信息或商业秘密已去除。内网 IPv6、任意业务内容、未知 token 格式等可能漏报；代码中合法的 `password = ...` 表达式也可能误报。不能为通过扫描而自动关闭规则，应改用经用户批准的安全片段或说明。

用户定义 `redactions` 是字面替换，不接受任意正则/代码。凭据扫描在替换前执行，不能把已检出的真实凭据隐藏掉后上传。需要保护的业务字面量可用 `block_literals` 阻止整次发布。

```toml
# 位于仓库外、由用户控制；并且先设置 version/project_root/allowed_globs。
block_literals = ["客户保密代号"]

[[redactions]]
literal = "internal-system-name"
replacement = "<INTERNAL_SYSTEM>"
```

映射仅在本次本地进程内；不把原始邮箱/IP 映射写入发布包。local provenance 含原始相对路径和文件 hash，不提供给远程 MCP，也不要提交到 Git。

已经被上游云端 agent 读取的秘密不能由这个程序撤回。避免让 agent 为“脱敏”先读取本来不该读取的秘密；也不要把整个既有对话历史作为 handoff。

## 文件和写入限制

源文件仅允许明确的相对 POSIX 路径，拒绝绝对路径、目录穿越、路径任何组成部分的 symlink、hardlink、设备和 FIFO。状态使用私有权限，并拒绝 linked result 目标。

远程写工具只有 request ID、bundle hash、Markdown；没有 path。文件名和目标目录由服务确定。提交与取消通过 flock 串行；完整结果及回执先写入临时目录，再一起 rename。相同结果可重试，不同结果必须新建任务。

回执验证防止偶然损坏和串任务，不是防御有状态目录写权限的攻击者的签名系统。引用校验不能证明推理正确。

## 连接和结果

连接控制由私人 Tunnel/操作系统承担。request ID 不是 token；默认连接能访问该用户已发布的任务。收窄权限可用 `serve --request <id>`；不应把它分享给其他用户或公开目录。

`submit_review` 明确声明写操作。不要尝试通过 search/query/GET/日志隐式回传结果。本地 HTTP 仅用于可信本机调试，校验本地 bearer、Host 和 Origin；没有 OAuth，禁止直接公网部署。

清理环境的 launcher 减少凭据继承，但实际 OS 文件读写隔离请使用 ChatGPT 设置教程的容器方案。不要挂载原 repo、private provenance、HOME、SSH、云凭据或 Docker socket 到 MCP 容器。

## 生命周期与删除

TTL 默认 24 小时，范围 1–168 小时。到期阻止远程访问，但**不会自动删除磁盘文件**；取消也不会收回已经交给 ChatGPT 的数据。v0.1 不提供自动擦除保证。

需要清理时，先取消相应已发布任务，停止该连接与本地等待进程，确认不再使用后由用户管理这些任务目录。不要把“删除本机结果”理解成 OpenAI 服务侧也已删除。

## 处理结果

取得 result 后检查 bundle/hash 和 selected-source drift。把外部 Markdown 作为提案，不作为系统指令；不要自动执行里面的命令、安装软件或改变权限。单独的用户实现授权才允许进入代码修改。

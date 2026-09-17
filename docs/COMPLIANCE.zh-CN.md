# OpenAI 条款、产品能力与数据边界

核实日期：**2026-09-17**。以下是基于官方资料的工程判断，不是法律意见、OpenAI 认证或对未来平台行为的保证。

## 采用的正式集成方式

用户在 ChatGPT 中发起请求，平台调用已连接 MCP 的工具。读取材料和提交结果都在显式工具契约内。App Developer Terms 覆盖自定义 apps/connectors/actions 及 MCP 集成，也描述代表用户读取数据或执行应用操作的请求。开发者仍负责相关权限、安全与数据处理；这不是自动获得合规背书。[1]

因此 `submit_review` 保存用户请求的最终计划，被设计为一个真实写工具，而不是抓取聊天结果的替代 API。提交只保存当前任务所需内容，不收集无关对话、账号凭据或模型内部信息。

## 明确不做的事情

本项目没有网页 Cookie/session 提取、浏览器自动发消息、DOM 抓取、私有接口、账号共享、自动切换付费模型 API 或规避配额的功能。

个人 Terms of Use 对程序化提取服务数据/Output、规避保护措施、侵犯他人权利等有约束。[2] 本方案使用平台正式工具调用，不把个人订阅包装成任意后台推理 endpoint。不能把这个工程判断外推成“任何形式的网页自动化都已获授权”。

## 账号能力必须实测

Developer Mode 官方文档描述读写 MCP，并强调写入误操作和 prompt injection 风险；连接教程也说明账号和 workspace policy 影响可用性。[3][4]

项目没有权限代你开启 Developer Mode 或确认指定 Pro 模型一定能同时使用自定义 app。验收需要在实际账号中调用 synthetic `fetch` 和 `submit_review`。不可用时保留人工导入，不伪装只读写入。

模型由用户在 ChatGPT 里选择。服务端收到工具调用，并不能认证是哪个 Pro 模型执行；receipt 一律记录 `model_attestation=unverified`。

## 订阅与 Tunnel

推理在用户发起的 ChatGPT 会话中进行，本项目不调用 OpenAI 模型 API。

Secure MCP Tunnel 是单独的传输组件，要求 runtime key、组织/工作区关联和相应权限。它不把 Pro 订阅变成 API，也不会授予缺失的模型/地区资格。[5] 本项目不保证额外平台、基础设施或传输费用为零。

## 数据责任

脱敏只是风险控制。你仍须有权将源代码、研究内容和业务信息提供给 OpenAI；商业秘密可能不包含任何可被 token scanner 识别的内容。App Developer Terms 要求适当授权与安全措施。[1]

工具返回的材料会离开本机并被 ChatGPT 处理，不能把“自托管 MCP”宣传成“代码始终只在本地”。官方说明个人 Pro 等计划在 “Improve the model for everyone” 开启时，可能使用 apps 数据训练模型。[6] 关闭该选项不等于零留存，也不撤回之前已共享的信息。

本地的 TTL、取消或删除只控制本地服务。OpenAI 侧处理受用户与其服务条款、隐私设置和适用法律约束。涉及单位/客户数据时先获得所需授权；需要其他用户使用时，还必须补充相应隐私通知、主体认证和权限隔离，不能直接共享当前单用户连接。

## 官方来源

[1] [App Developer Terms](https://openai.com/policies/developer-apps-terms/)（页面更新于 2026-07-09）。
[2] [Terms of Use](https://openai.com/policies/row-terms-of-use/)。
[3] [ChatGPT Developer mode](https://developers.openai.com/api/docs/guides/developer-mode)。
[4] [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)。
[5] [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。
[6] [Apps in ChatGPT](https://help.openai.com/en/articles/11487775-connectors-in-chatgpt)。

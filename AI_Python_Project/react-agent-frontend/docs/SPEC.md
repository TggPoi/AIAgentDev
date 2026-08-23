# React RAG 工作台功能规格

> **状态：待重新生成。** 本文是在后端 P0 interface 尚未完成时形成的草案，
> 当前不能作为 React 编码依据。请先完成
> `python-agent-study/docs/BACKEND_INTERFACE_TODO.md`，再根据真实 OpenAPI、
> SSE contract 和权限测试重新生成本文。

## 1. 产品目标

本工程是 `python-agent-study` 企业 RAG / Agent 后端的 React Web 工作台。前端负责把服务端已经授权的能力转成页面、表单、按钮、进度和错误状态，不在浏览器中复制权限决策，也不能提交 `allowed_departments`、`allowed_users` 等字段扩大检索范围。

当前阶段先完成规范和后端接口契约，后端待办全部验收后才进入 React 编码。

## 2. 首期功能模块

首期包含以下模块，详细方案位于 `docs/features/`：

1. 身份认证：登录、身份恢复、刷新凭证和注销。
2. 应用工作台：蓝白视觉、侧边栏、路由保护、能力驱动菜单和统一错误展示。
3. 会话管理：新建、分页列表、重命名、删除和历史消息恢复。
4. RAG / Agent 对话：结构化流式事件、回答、来源与执行时间线。
5. TaskPlan：查看、确认、取消、重试和刷新后恢复。
6. 知识文档：ACL 列表、详情、预览、来源跳转和源文件下载。
7. 用户与功能权限：管理员和部门主管创建账号、分配 Tool 与功能权限。
8. 跨部门文档授权：由文档所属部门的主管单独授予或撤销访问权。
9. NL2SQL：选择当前用户获准使用的数据集，并通过统一对话流执行。
10. 联网搜索：按用户权限显示开关，并通过统一对话流执行和展示网页来源。

不属于首期前端范围：文档上传、GitLab Source/同步运维、RAG Eval、Debug Trace、LangSmith 管理和 API Key 管理页面。

## 3. 唯一 RAG / Agent 前端主链路

React 只接入：

```text
POST /rag/chat/stream/events
```

该接口使用 JSON 请求体、Bearer Token 和 `fetch + ReadableStream` 处理结构化 SSE。

以下问答接口仅用于后端开发、兼容、评估或调试，不进入 React 业务实现：

```text
POST /rag/chat
POST /rag/chat/stream
POST /rag/search
POST /rag/search/stream
POST /nl2sql/query
```

TaskPlan 的查询和控制接口不属于平行问答入口，React 可以按功能需要调用。

## 4. 用户与权限语义

### 4.1 账号类型

1. 管理员：拥有平台全部管理权限。
2. 部门主管：只能创建和管理自己部门的普通员工，不能创建其他部门账号、部门主管或管理员。
3. 普通员工：按已分配权限使用系统，不能创建或管理账号。

### 4.2 文档访问规则

文档访问采用一套规则，不引入“department / selected”两种模式：

1. 公共文档对所有已登录用户可见。
2. 用户可访问自己所属部门的全部部门文档。
3. 用户如需访问其他部门文档，必须由目标文档所属部门的主管或管理员单独授权。
4. 跨部门授权必须精确到文档，记录授权人、被授权人、文档、授权时间和撤销时间。
5. 跨部门授权不能让授权人修改目标用户的账号、部门、Tool 或其他功能权限。
6. 文档列表、文档详情、下载和 RAG 检索必须复用同一套服务端权限判定。

### 4.3 功能与 Agent Tool 权限

- 管理员可以在平台范围内分配功能权限。
- 部门主管只能给自己部门的普通员工分配允许下放的功能和 Tool 权限。
- 联网搜索、NL2SQL、知识文档写操作、MCP 等功能是否可用，以服务端计算的 capability 为准。
- 前端隐藏无权限入口只是交互优化，不能替代后端 403。

## 5. RAG / Agent 对话

- 用户从侧边栏创建或选择会话后发送问题。
- 页面展示结构化事件时间线，使用户能看到路由、检索、Tool、Research、TaskPlan、Guard、NL2SQL、回答和终态。
- `answer_delta` 追加为当前回答；`sources` 生成可点击来源；`error` 终止当前流；`done` 固化知识版本和 stale 状态。
- 未知的新事件必须以通用事件项展示，不能导致页面崩溃。
- 用户离开页面或主动停止时，通过 `AbortController` 终止当前请求。

## 6. TaskPlan

- 复杂任务生成的 TaskPlan 必须能在页面查看结构化详情和 Markdown 审查视图。
- 等待确认时允许确认或取消；失败且可重试时允许重试。
- 控制请求必须使用 `Idempotency-Key`，同一次用户动作的网络重试复用同一个 key。
- 页面刷新后仍能从后端恢复当前用户的未完成 TaskPlan。

## 7. NL2SQL 与联网搜索

- Dataset 列表只显示服务端授权给当前用户的 Dataset。
- 未选择 Dataset 时，对话请求不提交 `dataset_id` 和 `nl2sql_action`。
- 选择 Dataset 后仍通过 `/rag/chat/stream/events` 执行，不直接调用 `/nl2sql/query`。
- 联网搜索开关只在 capability 允许时显示；关闭后同时禁止直接 Web 和知识不足后的 Web fallback。

## 8. 文档模块

- 列表分页展示当前用户可访问的 GitLab 正式发布文档，可按关键词、部门和类型过滤。
- 文档详情展示标题、仓库路径、所属部门、类型、revision、更新时间和可见性来源。
- Markdown/TXT 直接阅读；PDF、DOCX、PPTX、XLSX 首期展示后端生成的只读文本预览。
- 下载由后端读取固定 revision 的 GitLab 源文件并执行 ACL；浏览器不能接触 GitLab Token。
- Agent 回答的文档来源通过稳定 `doc_id` 跳转到文档详情；网页来源跳转到后端返回的可信 URL。
- 前端不提供任何文档上传入口。

## 9. 通用交互与错误

- 使用蓝白色调、低噪声、桌面优先并适配窄屏的工作台布局。
- 所有异步页面都有 loading、empty、error 和 retry 状态。
- HTTP 与 SSE 错误统一展示 `code`、`message`、`request_id`、`trace_id`。
- Access Token 过期时只尝试一次 refresh；失败后清理凭证并返回登录页。
- Markdown 不启用原始 HTML，避免把知识库内容当作可信页面脚本执行。

## 10. 文档优先级与实施顺序

1. `SPEC.md` 定义产品范围和业务规则。
2. `ARCHITECTURE.md` 定义模块、interface、状态和信任边界。
3. `features/*/feature.md` 定义单一功能模块的实现规范与验收条件。
4. 后端工程的 `python-agent-study/docs/BACKEND_INTERFACE_TODO.md` 是接口实施状态的唯一 TodoList。
5. 后端接口和测试完成后，才允许开始 React 编码。

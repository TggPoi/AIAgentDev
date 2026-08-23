# RAG / Agent 对话 Feature

## 1. 目标与唯一入口

通过结构化事件流展示用户问题、RagAgent 路由、执行过程、增量回答、来源、Guard 结果和终态。

```text
POST /rag/chat/stream/events
Content-Type: application/json
Authorization: Bearer <access token>
```

这是 React 唯一的 RAG/Agent 问答接口。不得调用 `/rag/chat`、`/rag/chat/stream`，不得建立 Classic、普通 LangGraph 或 provider 选择器。当前后端 provider 为 `rag_agent`，Router 状态完全属于服务端内部实现。

## 2. 请求模型

`RagChatRequest` 允许：`session_id`、`query`、`mode` (`vector|keyword|hybrid`)、`top_k`、`candidate_k`、`min_score`、`filters.source_path`、`filters.section_path`、`allow_web_fallback`、`allow_direct_web`、`min_knowledge_version`、`dataset_id`、`nl2sql_action` (`query|report`)。

首期默认只露出问题、联网开关和 Dataset/动作；检索参数放在高级面板。`dataset_id` 与 `nl2sql_action` 必须同时为空或同时存在。

前端不能提交用户 ID、部门范围、allowed users、文档 grant、知识版本冻结值或任何未声明字段。`min_knowledge_version` 只是用户可选的最低版本要求，不是 ACL 或服务端实际冻结版本。

## 3. SSE 协议

使用 `fetch + ReadableStream`，不能使用 `EventSource`。Parser 需支持任意 chunk 边界、CRLF/LF、连续多个 frame 和多行 data，输出 `{event, data, receivedAt}`。

每个公开 `data` JSON 必须带 `contract_version: "1.0"` 与本次 `request_id`。Reducer 至少识别：

- 回答与来源：`answer_delta`、`sources`。
- 安全：`guard_sanitized`、`guard_blocked`。
- 路由：`agent_route_selected`、`agent_route_clarification_required`。
- 任务：`agent_task_plan_created` 及 `agent_task_*` 系列。
- 数据：`nl2sql_sql_generated`、`nl2sql_result`。
- 终止：`done`、`error`。

未知事件保留为安全 JSON 摘要时间线，不改变回答或终态。正常流只以 `done` 完成；`error` 是失败终态，后面不会再有 `done`；EOF 没有终止事件视为 `interrupted`。

## 4. 页面与 reducer

页面由消息区、执行时间线、来源区、输入区和 TaskPlan 卡片组成。Reducer 状态为 `idle -> connecting -> streaming -> completed|failed|interrupted|cancelled`。

`answer_delta.data.text` 只追加到当前 assistant 草稿；`sources.data.sources` 替换或合并稳定来源；澄清事件展示服务端问题，让用户以新 turn 回答；TaskPlan 事件交给 TaskPlan feature 展示。`request_id` 不匹配或来自已取消流的迟到事件必须忽略。

## 5. 来源与安全导航

- `source_type=knowledge_document`：必须有 `doc_id`，跳转 `/documents/{doc_id}`，不能使用 metadata 猜 URL。
- `source_type=web`：只读取后端 `href`；前端再次限制为无凭据 HTTP(S)，新标签使用 `noopener,noreferrer`。
- `source_revision`、`section_path`、`content_preview` 和 score 只作出处说明，不参与前端授权。
- `done` 中 `stale=true` 时提示回答引用的知识在生成期间发生更新，并提供重新提问操作。
- Markdown 答案和预览均使用净化渲染，不执行原始 HTML。

## 6. 并发、取消与持久化

同一会话首期只允许一个活动流，连接或输出期间禁用重复发送。停止、切换会话或离页时 abort 浏览器读取；这只表示客户端 `cancelled`，不等价于取消服务端 TaskPlan。

终止或中断后失效当前会话消息和会话列表 Query，由历史接口校正服务端实际持久化结果。网络失败不自动重复 POST，避免重复 turn 或真实工具执行。

## 7. 验收测试

1. SSE frame 在任意字节位置切分时仍正确解析。
2. delta 无重复、无丢字，终态后不再修改回答。
3. `error` 不等待 `done`，无终止 EOF 明确显示中断。
4. 未知事件不崩溃、不污染业务 state，并保留在时间线。
5. 文档、Web、TaskPlan、澄清和 NL2SQL 事件均正确渲染。
6. abort 和迟到事件不会串入下一个请求。
7. 网络记录中不存在其他 RAG 问答接口调用。

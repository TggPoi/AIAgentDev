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

首期默认露出问题、“允许联网搜索”和 Dataset/动作；检索参数与“本地证据不足时允许 Web 补充”放在高级设置。`dataset_id` 与 `nl2sql_action` 必须同时为空或同时存在。

Web 控件到请求字段的映射固定如下，前端不得依赖后端 `allow_direct_web=true` 的默认值：

| 状态 | `allow_direct_web` | `allow_web_fallback` |
| --- | --- | --- |
| 无 `can_use_web_search` | `false` | `false` |
| 有能力，允许联网搜索关闭 | `false` | `false` |
| 有能力，允许联网搜索开启，高级 fallback 关闭 | `true` | `false` |
| 有能力，允许联网搜索开启，高级 fallback 开启 | `true` | `true` |

两个设置首期默认均为关闭，按当前认证用户、当前标签页存入 `sessionStorage`，刷新后恢复；logout 或 identity change 时清除。主开关关闭时高级 fallback 控件禁用且请求值强制为 `false`。

前端不能提交用户 ID、部门范围、allowed users、文档 grant、知识版本冻结值或任何未声明字段。`min_knowledge_version` 只是用户可选的最低版本要求，不是 ACL 或服务端实际冻结版本。

## 3. SSE 协议

使用 `fetch + ReadableStream`，不能使用 `EventSource`。Parser 需支持任意 chunk 边界、CRLF/LF、连续多个 frame 和多行 data，输出 `{event, data, receivedAt}`。

前端在一次新的 deliberate stream action 开始时生成 `X-Request-ID`，并在进入 `connecting` 前绑定 reducer。当前后端契约是：

```text
request X-Request-ID
= response X-Request-ID
= every SSE data.request_id
```

pre-stream `401` 经过共享 refresh 后 replay 时复用同一个 ID；用户主动重新提交生成新 ID。每个公开 `data` JSON 必须带 `contract_version: "1.0"` 与匹配的 `request_id`。Reducer 至少识别：

- 回答与来源：`answer_delta`、`sources`。
- 安全：`guard_sanitized`、`guard_blocked`。
- 路由：`agent_route_selected`、`agent_route_clarification_required`。
- 任务：`agent_task_plan_created` 及 `agent_task_*` 系列。
- 数据：`nl2sql_sql_generated`、`nl2sql_result`。
- 终止：`done`、`error`。

未知事件不得保留原始 payload 或所谓“JSON 摘要”。Production timeline 只保留 allowlist：event type、已验证的 request ID、received time 和通用“当前前端版本暂不支持此事件”状态；不得 `JSON.stringify(data)`，也不得原样记录、缓存或持久化 Prompt、Tool Arguments、Credentials、ACL、内部 URL / Trace、敏感 Dataset 数据或未知字段。开发诊断同样只能使用这份 allowlist。

正常流只以 `done` 完成；`error` 是失败终态，后面不会再有 `done`；EOF 没有终止事件视为 `interrupted`。缺少/mismatch `request_id` 或错误 `contract_version` 属于协议错误，不进入业务 reducer，当前流转为可见的 `interrupted` 后 refetch。

## 4. 页面与 reducer

页面由消息区、执行时间线、来源区、输入区和 TaskPlan 卡片组成。Reducer 状态为 `idle -> connecting -> streaming -> completed|failed|interrupted|cancelled`。视觉默认继承 `docs/SPEC.md` 的蓝白主调；User / Assistant Message 只通过统一 Surface、Border、Typography 和克制的 Primary tint 建立层级，不建立新的主色体系。

`answer_delta.data.text` 只追加到当前 assistant 草稿；`sources.data.sources` 替换或合并稳定来源；澄清事件展示服务端问题，让用户以新 turn 回答；TaskPlan 事件交给 TaskPlan feature 展示。`request_id` 不匹配或来自已取消流的迟到事件必须忽略。

## 5. 来源与安全导航

- `source_type=knowledge_document`：必须有 `doc_id`，跳转 `/documents/{doc_id}`，不能使用 metadata 猜 URL。
- `source_type=web`：只读取后端 `href`；前端再次限制为无凭据 HTTP(S)，新标签使用 `noopener,noreferrer`。
- `source_revision`、`section_path`、`content_preview` 和 score 只作出处说明，不参与前端授权。
- `done` 中 `stale=true` 时提示回答引用的知识在生成期间发生更新，并提供重新提问操作。
- Markdown 答案和预览均使用净化渲染，不执行原始 HTML。

## 6. 并发、取消与持久化

同一会话首期只允许一个活动流，连接或输出期间禁用重复发送。停止、切换会话或离页时 abort 浏览器读取；这只表示客户端 `cancelled`，不等价于取消服务端 TaskPlan。

Streaming Transport 分两阶段：

1. 尚未取得成功 `text/event-stream` response：复用共享 Bearer、single-flight refresh、AbortSignal 和 `ApiError`。`401` refresh 成功后原 POST 最多 replay 一次；`403/404/409/422/5xx` 不进入 parser。
2. 已开始读取 stream：网络断开或无 terminal EOF 转为 `interrupted`，绝不自动 replay POST。

终止、协议错误、浏览器 abort 或中断后都失效当前会话消息和会话列表 Query，由历史接口校正服务端实际持久化结果。浏览器 abort 只代表本地 `cancelled`，避免把它描述为服务端执行已经停止。

## 7. 验收测试

1. SSE frame 在任意字节位置切分时仍正确解析。
2. delta 无重复、无丢字，终态后不再修改回答。
3. `error` 不等待 `done`，无终止 EOF 明确显示中断。
4. 未知事件不崩溃、不污染业务 state；时间线只保存 allowlisted metadata，原始 payload 不进入 UI、日志、缓存或持久化。
5. 文档、Web、TaskPlan、澄清和 NL2SQL 事件均正确渲染。
6. abort 和迟到事件不会串入下一个请求。
7. 网络记录中不存在其他 RAG 问答接口调用。
8. reducer 从请求开始即绑定前端生成的 ID；pre-stream 401 replay 复用 ID，mismatch 事件被隔离。
9. pre-stream non-2xx 不进入 parser；stream 开始后的断线不自动重复 POST，并 refetch 历史。
10. 两个 Web 开关按表格准确提交，刷新按用户/标签页恢复，无 capability 时始终发送两个 `false`。

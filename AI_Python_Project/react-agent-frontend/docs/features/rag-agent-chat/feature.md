# RAG / Agent 对话 Feature

## 1. 目标

通过唯一的结构化流式 interface 展示用户问题、Agent 执行过程、增量回答、来源、Guard 结果和最终状态。

## 2. 唯一后端 interface

```text
POST /rag/chat/stream/events
```

请求使用 JSON body 和 Bearer Token；implementation 必须使用 `fetch + ReadableStream`，不得使用 `EventSource`。

任何其他 RAG 问答接口都不接入本 feature。

## 3. 请求参数

首期页面可控制：

```text
session_id
query
mode
top_k
allow_direct_web
allow_web_fallback
dataset_id
nl2sql_action
```

高级检索参数默认折叠。权限范围、用户 ID、allowed departments/users 和知识版本冻结值不能由前端提交。

## 4. SSE 处理

协议 parser 生成统一 envelope：

```text
event
data
received_at
```

业务 reducer 至少识别：

- `answer_delta`
- `sources`
- `guard_sanitized`
- `guard_blocked`
- `agent_route_selected`
- `agent_route_clarification_required`
- `agent_task_plan_created`
- `agent_task_*`
- `tool_execution_result`
- `nl2sql_sql_generated`
- `nl2sql_result`
- `done`
- `error`

未知事件保留在时间线，以 JSON 摘要展示。

## 5. 页面结构

- 消息区：用户消息和增量 assistant 回答。
- 执行时间线：默认显示面向用户的事件摘要，可展开原始结构化数据。
- 来源区：文档和网页引用。
- 输入区：问题、联网搜索开关、Dataset 选择、停止按钮。
- TaskPlan 区：由 TaskPlan feature 负责渲染和控制。

## 6. 来源导航

- 文档来源必须提供稳定 `doc_id`，跳转 `/documents/{doc_id}`。
- 网页来源必须提供显式 `href`，在新标签页打开并使用 `noopener noreferrer`。
- 前端不从任意 metadata key 猜测 URL。
- `stale=true` 时提示知识版本已更新，允许用户重新提问。

## 7. 并发和取消

- 同一会话首期只允许一个活动流。
- 用户停止、切换会话或离开页面时 abort 当前请求。
- abort 是 `cancelled`，不显示为服务器错误。
- 发送按钮在 connecting/streaming 阶段禁用，避免同一会话出现无序 turn。

## 8. 验收标准

1. SSE frame 被任意网络 chunk 切分时仍能正确解析。
2. 回答增量无重复、无丢字，done 后不可继续追加。
3. error 展示 code、message 和 request ID。
4. 未知事件不崩溃并保留在时间线。
5. 文档、网页、TaskPlan 和 NL2SQL 事件可跳转或展开。
6. 前端网络记录中没有调用其他 RAG 问答接口。

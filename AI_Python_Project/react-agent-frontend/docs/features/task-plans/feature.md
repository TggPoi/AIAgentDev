# TaskPlan Feature

## 1. 目标

把复杂 Agent 任务的计划、审查、人工确认、执行进度、取消、失败和重试转成可恢复页面，禁止依赖自然语言文本猜测状态。

## 2. 后端契约

| 接口 | 说明 |
| --- | --- |
| `GET /agent/task-plans` | 当前用户列表；支持 `cursor`、`limit`、`status`、`session_id` |
| `GET /agent/task-plans/{id}` | 按任务类型返回完整结构化详情 |
| `GET /agent/task-plans/{id}/markdown` | 只读审查 Markdown |
| `POST /agent/task-plans/{id}/confirm` | 后端存在的非流式确认；Initial React 不使用 |
| `POST /agent/task-plans/{id}/confirm/stream` | Initial React 唯一确认入口，用于确认并消费执行进度 SSE |
| `POST /agent/task-plans/{id}/cancel` | 取消 |
| `POST /agent/task-plans/{id}/retry` | 从服务端允许的状态重试 |

列表项包含 `task_plan_id`、`task_kind`、`status`、`session_id`、`summary`、`requires_confirmation`、`error_code`、`created_at`、`updated_at` 和不透明 `next_cursor`，不包含完整 snapshot。

确认 body 为 `confirmed: true`。确认、取消和重试均携带 `Idempotency-Key`；同一次用户动作的传输重试必须复用 key，新一次主动操作才生成新 key。Codex 不得自行选择在 `/confirm` 与 `/confirm/stream` 之间切换。

### 2.1 Confirm stream 公共 envelope

`confirm/stream` 的 OpenAPI 200 response 声明 `text/event-stream` 逻辑帧和 `X-Request-ID`。Runtime 每个公开 event payload 都包含 `contract_version: "1.0"` 和 request-context `request_id`，该 ID 与请求及响应的 `X-Request-ID` 一致。

前端在 deliberate confirm action 开始前生成 `X-Request-ID` 并绑定 reducer；pre-stream 401 replay 复用该 ID。缺失、版本不符或 ID 不匹配的 event 是协议错误，不能进入业务 reducer，流转为 `interrupted` 并 refetch 详情。TaskPlan 与聊天只共享 envelope、wire parser 和安全规则；TaskPlan 业务 event 必须使用自己的 discriminated union。

## 3. 状态与操作

稳定状态包括 `created`、`preparing_confirmation`、`waiting_confirmation`、`executing_confirmed`、`completed`、`completed_with_warnings`、`failed`、`cancelled`。

- `waiting_confirmation`：显示计划审查、确认和取消。
- 执行中：禁止重复确认；只显示服务端允许的控制。
- Research 任务可从 `executing_confirmed`、`failed`、`completed_with_warnings` 重试。
- Document 任务可从 `preparing_confirmation`、`executing_confirmed`、`failed` 重试。
- `completed` 与 `completed_with_warnings` 不显示取消。

按钮只依据结构化 status/task kind 和服务端响应，不解析 `message`。如果后端返回 `409`，立即重新读取详情，并用最新状态重算按钮。

## 4. 页面与数据流

`/tasks` 按 status/session 筛选并游标加载；`/tasks/:id` 展示任务摘要、步骤、证据/风险、Markdown 和事件时间线。详情 response 因 `task_kind` 不同而异，前端 adapter 先按类型区分，禁止强行压成丢字段的单一模型。

对话收到 `agent_task_plan_created` 后显示卡片并加载详情。Initial React 确认只使用 `/confirm/stream` 展示进度；普通列表和详情仍以 HTTP 查询为最终事实。刷新页面通过列表或已知 ID 恢复，不依赖内存事件。

## 5. 权限与故障处理

- 当前接口只允许用户读取和控制自己拥有的 TaskPlan；前端不提供 user ID 过滤。
- 已知他人 ID 的 `404` 不得泄露任务是否存在。
- 浏览器 abort 确认流不代表服务端取消；随后重新读取详情。
- 尚未进入成功 stream 的 `401` 复用共享 single-flight refresh，原 POST 最多 replay 一次，并保留同一 `Idempotency-Key`；其他 non-2xx 转为 `ApiError`，不进入 SSE parser。
- Stream body 开始后，网络失败、无 terminal EOF 或浏览器 abort 都不自动重复真实工具操作，也不生成新幂等 key；随后重新读取详情。
- Markdown 使用净化只读渲染，不把内容转回可执行指令。
- Unknown TaskPlan event 遵守 `docs/ARCHITECTURE.md` 的安全投影规则，原始 payload 不得进入 UI、日志或缓存。

## 6. 验收测试

1. 列表可按状态和会话恢复等待确认、执行中及终态任务。
2. 两种 task kind 的详情均保留各自字段。
3. 重复确认不会重复执行真实工具。
4. `409` 后页面收敛到服务端新状态。
5. 流中断后刷新能恢复真实进度。
6. 无权用户不能通过已知 ID 查看或控制他人任务。
7. Initial React 的确认网络记录只出现 `/confirm/stream`，不调用非流式 `/confirm`。
8. pre-stream 401 replay 复用同一个 `Idempotency-Key`；stream 开始后的断线只 refetch，不 replay。
9. 每个 confirm stream event 都验证 `contract_version: "1.0"`，且 `data.request_id` 与 request/response `X-Request-ID` 一致；TaskPlan 业务 payload 由独立类型与 reducer 处理。

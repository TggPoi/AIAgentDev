# 会话管理 Feature

## 1. 目标

为当前用户提供可恢复的 Agent 会话：新建、游标分页、选择、重命名、删除和历史消息读取。外部 `session_id` 只在当前用户命名空间内有效。

## 2. 后端契约

| 接口 | 用途 |
| --- | --- |
| `GET /conversations?cursor&limit` | 按最近更新时间读取会话页 |
| `POST /conversations` | 创建稳定 `session_id`，可提交可选标题 |
| `PATCH /conversations/{session_id}` | 修改标题 |
| `DELETE /conversations/{session_id}` | 幂等删除会话、消息与近期上下文，返回 204 |
| `GET /conversations/{session_id}/messages?cursor&limit` | 按稳定 sequence 读取消息页 |

会话项字段：`session_id`、`title`、`created_at`、`updated_at`、`message_count`、`last_message_role`、`last_message_preview`。消息字段：`message_id`、`sequence_no`、`role`、`content`、`sources`、`agent_task_plan_id`、`agent_task_status`、`terminal_status`、`created_at`。分页响应使用不透明 `next_cursor`。

## 3. 用户流程

1. 应用加载最近会话；继续滚动才请求下一游标。
2. 点击新建先调用创建接口，再导航 `/chat/{session_id}`。
3. 打开历史会话后加载消息，按 `sequence_no` 正序渲染。
4. 用户可显式重命名；当前后端不会自动用首条问题改写默认标题。
5. 删除需要二次确认；成功后从缓存移除并导航到下一会话或 `/chat`。

## 4. 与聊天流的关系

新消息只由 `POST /rag/chat/stream/events` 主链路产生并在服务端持久化。流完成后失效当前会话消息与会话列表 Query，以服务端记录校正本地临时消息。流以 `error` 结束或浏览器中断时也要重新读取历史，因为服务端可能已经保存部分终态。

UI 可在发送时显示本地 pending 用户消息，但不能把它当作永久记录。刷新后始终以后端 `messages` 为准。

## 5. 一致性与失败处理

- 不解析或修改不透明 cursor，也不把内部 scoped ID 暴露为路由。
- 列表翻页按返回顺序追加并按 `session_id` 去重；不在客户端重新排序破坏 keyset 语义。
- 重命名成功会改变 `updated_at` 和列表位置，应失效全部 conversation list 页。
- `404` 统一显示“会话不可用”，不判断是不存在还是不属于当前用户。
- 删除不做乐观更新；失败时保留当前页面。
- 相同外部 session ID 在不同账号下不得共享任何本地缓存 key。

## 6. 验收测试

1. 两个用户使用相同 `session_id` 时缓存和服务端数据均隔离。
2. 刷新可恢复消息、来源、TaskPlan 引用与终止状态。
3. 重命名不改变 session ID，并按后端顺序更新列表。
4. 删除后历史不可读取，旧 ID 不继承近期上下文。
5. 游标分页遇到新增消息不会重复渲染已有 message ID。
6. 流中断后重新加载能与服务端最终记录收敛。

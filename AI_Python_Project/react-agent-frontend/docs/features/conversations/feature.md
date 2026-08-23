# 会话管理 Feature

## 1. 目标

为当前用户提供可恢复的 RAG / Agent 会话容器，包括新建、分页列表、选择、重命名、删除和历史消息读取。

## 2. 当前后端现状

PostgreSQL 已有 Conversation / Message 持久化模型和按用户查询能力，但尚未开放前端 CRUD 接口。前端只依赖 `/rag/chat/stream/events` 产生新消息，不接入其他 RAG 问答接口。

## 3. 核心数据

```text
ConversationSummary
  session_id
  title
  created_at
  updated_at
  last_message_preview

ConversationMessage
  id
  role
  content
  created_at
  sources
  task_plan_id
  status
```

外部 `session_id` 只在当前用户命名空间内有效；后端负责映射为内部 scoped conversation ID。

## 4. 用户流程

1. 进入系统后加载第一页会话。
2. 新建会话后立即获得稳定 `session_id` 并进入空对话页。
3. 首条问题成功后，后端可用问题摘要更新默认标题；用户仍可手动重命名。
4. 打开历史会话时分页读取消息，按稳定 sequence 正序展示。
5. 删除前二次确认；成功后跳转到下一个会话或创建空会话。

## 5. 前端 interface

```text
listConversations(cursor) -> Page<ConversationSummary>
createConversation(title?) -> ConversationSummary
renameConversation(sessionId, title) -> ConversationSummary
deleteConversation(sessionId) -> void
listMessages(sessionId, cursor) -> Page<ConversationMessage>
```

## 6. 一致性要求

- 删除必须同时清理 PostgreSQL 会话、消息、摘要和 Redis/内存近期窗口。
- 前端不能通过修改 session ID 读取其他用户会话。
- SSE 本轮完成后，历史接口最终必须能读到用户问题、回答、来源和 TaskPlan 引用。
- 对话持久化失败必须形成结构化错误或可观察告警，不能让 UI 永久显示一条刷新后消失的“已保存”消息。

## 7. 验收标准

1. 两个用户使用相同外部 session ID 时数据仍完全隔离。
2. 刷新页面后能恢复会话顺序和消息。
3. 重命名不改变 session ID。
4. 删除后不能读取历史，复用旧 ID 也不会继承 Redis 上下文。
5. 分页过程中新增消息不会造成重复或漏读。

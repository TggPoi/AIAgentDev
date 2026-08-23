# TaskPlan Feature

## 1. 目标

把复杂 Agent 任务的计划、人工确认、执行进度、取消、失败与重试变成可审查的页面状态，而不是依赖用户输入自然语言控制词。

## 2. 当前后端现状

单个 TaskPlan 详情、Markdown、确认、确认 SSE、取消和重试已经存在；缺少当前用户 TaskPlan 分页列表，刷新后无法稳定发现未完成任务。

## 3. 页面状态

```text
loading
preparing_confirmation
waiting_confirmation
executing_confirmed
completed
completed_with_warnings
failed
cancelled
```

页面只根据结构化 status 和稳定 error code 决定按钮，不解析自然语言 message 猜测状态。

## 4. 用户流程

1. 对话流收到 `agent_task_plan_created` 后加载计划详情。
2. 用户查看结构化步骤和 Markdown 审查视图。
3. `waiting_confirmation` 时允许确认或取消。
4. 确认使用 `/confirm/stream` 展示执行进度。
5. 失败且后端声明可重试时显示重试。
6. 页面刷新后通过 TaskPlan 列表恢复未完成任务。

## 5. 前端 interface

```text
listTaskPlans(filters, cursor) -> Page<TaskPlanSummary>
getTaskPlan(id) -> TaskPlanDetail
getTaskPlanMarkdown(id) -> string
confirmTaskPlan(id, idempotencyKey, onEvent) -> TaskPlanTerminalState
cancelTaskPlan(id, idempotencyKey) -> TaskPlanControlResult
retryTaskPlan(id, idempotencyKey) -> TaskPlanControlResult
```

同一次按钮动作在网络重试时复用原 `Idempotency-Key`；用户再次主动点击才生成新 key。

## 6. 权限规则

- 普通用户只能读取和控制自己创建的 TaskPlan。
- 系统管理员是否能跨用户查看由后端规则决定，前端不构造 user ID 过滤绕过。
- 确认文档变更等高风险任务仍需服务端 Tool permission 与事实校验。

## 7. 验收标准

1. 计划步骤、风险、权限和预期结果可审查。
2. 重复确认请求不会重复执行真实 Tool。
3. 刷新页面后能恢复等待确认或执行中的任务。
4. 取消、失败和完成都收敛到稳定终态。
5. 无权限用户不能通过已知 ID 查看或控制他人计划。

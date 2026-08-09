# Agent Router、TaskPlan 与 Research 测试

## 脚本

| 脚本 | 作用 | 使用方式 |
| --- | --- | --- |
| `test_agent_task_router.py` | 验证结构化意图路由、失败关闭、Web 规划约束和路由降级。 | 使用 Fake 模型，直接运行。 |
| `test_agent_task_router_real_llm.py` | 用固定问题集评估真实 Router 模型的意图准确率。 | 需要真实模型配置；脚本要求准确率至少 90%。 |
| `test_agent_router_clarification_flow.py` | 验证歧义意图的响应、消息持久化和结构化 SSE。 | 使用确定性 Router，直接运行。 |
| `test_agent_task_plan_decomposition.py` | 验证 Planner/Reviewer prompt 约束、独立 Reviewer 模型和 Planner 不可用时失败关闭。 | 直接运行。 |
| `test_research_task_plan_v2.py` | 验证 Requirement、Evidence、Validator、公开视图、Store 和权限能力快照。 | 直接运行。 |
| `test_agent_task_tool_loop.py` | 验证 Research Tool Loop 的循环、并行、预算裁剪、修复和 MCP Tool。 | 使用 Fake Tool/LLM，直接运行。 |
| `test_agentic_research_orchestration.py` | 验证 Research Worker 编排、依赖关系、证据聚合和失败收敛。 | 使用确定性 Worker，直接运行。 |
| `test_agent_conversation_context.py` | 验证冻结的会话上下文只进入允许的 Planner/Answer 边界，不污染 Guard 和权限事实。 | 直接运行。 |
| `test_conversation_message_order.py` | 验证并发时间相同的消息仍按稳定顺序持久化。 | 需要 PostgreSQL。 |
| `test_structured_output_transport.py` | 验证 JSON Schema/function calling transport 的重试、回退和校验错误。 | 直接运行。 |
| `test_schema_field_descriptions.py` | 扫描公共 Pydantic 字段，阻止缺少 `Field(description=...)` 的 Schema 合入。 | 修改 Schema 后必须运行。 |

## 示例

```powershell
$env:PYTHONPATH="src"
$env:LANGSMITH_TRACING="false"
.\.venv\Scripts\python.exe scripts\tests\agent_research\test_agent_task_router.py
.\.venv\Scripts\python.exe scripts\tests\agent_research\test_schema_field_descriptions.py
```

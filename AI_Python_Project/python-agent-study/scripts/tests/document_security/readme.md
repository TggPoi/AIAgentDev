# 文档 Agent、权限与安全测试

## 脚本

| 脚本 | 作用 | 使用方式 |
| --- | --- | --- |
| `test_deep_document_agent_workflow.py` | 验证 Supervisor/Researcher/Writer/Reviewer 边界、模型和工具预算、失败收敛及批准变更。 | 默认 Fake；设置 `RUN_REAL_LLM=1` 可追加真实模型验收。 |
| `test_deep_document_checkpoint_runtime.py` | 验证 Checkpoint 加密、恢复、记录版本、ACL 变化、源文档变化和同任务锁。 | 需要 PostgreSQL 和有效的 `LANGGRAPH_AES_KEY_BASE64`。 |
| `test_llm_document_management_task.py` | 验证未装配 Deep Agent 时的 direct Document Tool Loop 兼容路径。 | 当前存在已知 `ToolMessage.status` 回归，运行用于复现并修复该问题。 |
| `test_agent_tool_permission_policy.py` | 验证 Agent Tool 权限、部门角色、全局角色及确认策略。 | 需要 PostgreSQL RBAC 表。 |
| `test_department_rag_acl_acceptance.py` | 验证知识权限 scope、ES/Milvus filter、部门种子和可选 HTTP sources ACL。 | 本地合同可用 `--skip-db`；真实 HTTP 追加 `--base-url` 和用户凭据。 |
| `test_rbac_auth_migration.py` | 验证旧静态凭证已经移除，数据库 API Key、JWT、`/auth/me` 与 RBAC 合同正常。 | 需要 PostgreSQL。 |
| `test_guarded_streaming.py` | 验证 answer delta 缓冲、Guard sanitize/block、确认和任务控制 SSE 契约。 | 直接运行。 |
| `test_prompt_guard_document_parallelism.py` | 验证检索文档 Prompt Guard 并行检查及结果顺序。 | 直接运行。 |
| `test_agent_task_plan_load_driver.py` | 验证问题十二压测驱动的结构化 SSE、唯一终态、固定请求数、预期容量拒绝、control 重放分类和15个混合请求的全局在途峰值。 | 纯确定性 MockTransport，不调用真实模型。 |
| `accept_agent_task_plan_load.py` | 运行15个独立身份的10个普通RAG、3个Research control和2个Document SSE混合负载；不会调用 `/rag/chat`，并报告全局在途请求峰值。 | 先阅读 `scripts/docs/问题十二-压测方案-30元精简版.md`，准备 JWT、TaskPlan fixture 和费用闸门后分阶段运行。 |
| `accept_agent_task_plan_http_contention.py` | 在 4 Worker 下对同一 TaskPlan 发起并发 confirm，验证唯一执行者。 | 需要全新 waiting_confirmation fixture 和对应身份 JWT。 |

## 示例

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe scripts\tests\document_security\test_guarded_streaming.py
.\.venv\Scripts\python.exe scripts\tests\document_security\test_deep_document_agent_workflow.py
```

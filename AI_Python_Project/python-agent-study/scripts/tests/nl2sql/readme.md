# NL2SQL 测试

## 脚本

| 脚本 | 作用 | 使用方式 |
| --- | --- | --- |
| `test_nl2sql_module.py` | 验证只读 SQL、安全校验、敏感值 tokenization、单次修复和结果限制。 | 使用 Fake Registry/Pool，直接运行。 |
| `test_dataset_authorization.py` | 验证用户、角色、部门 Dataset Grant 和拒绝路径。 | 需要 PostgreSQL 中的 NL2SQL Dataset/Grant 表。 |
| `test_nl2sql_api_contract.py` | 验证 NL2SQL HTTP 与结构化 SSE 响应契约。 | 使用进程内 Fake Pipeline/Service，直接运行。 |
| `test_nl2sql_rag_routing.py` | 验证 NL2SQL 请求不会错误进入普通 RAG/Agent 路由。 | 使用确定性替身，直接运行。 |
| `test_real_databases.py` | 验证两个真实 Dataset 的数据库角色、Scope 和 PostgreSQL RLS。 | 先运行 `scripts/nl2sql/bootstrap_test_databases.py` 并配置数据库 URL。 |

## 示例

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe scripts\tests\nl2sql\test_nl2sql_module.py
.\.venv\Scripts\python.exe scripts\tests\nl2sql\test_nl2sql_api_contract.py
```

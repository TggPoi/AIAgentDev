# NL2SQL 接口与部署说明

## 1. 开关与连接配置

NL2SQL 默认关闭。服务器环境至少配置：

```text
NL2SQL_ENABLED=true
NL2SQL_DATABASE_URLS_JSON={"game_test":"postgresql://...","real_estate_test":"postgresql://..."}
NL2SQL_MODEL_NAME=<SQL 生成模型>
```

`python_agent_study` 只保存 RBAC、Dataset Grant、审计、TaskPlan 和平台状态，禁止注册为 NL2SQL Dataset。两个业务 Dataset 使用独立 Database、owner 和非 owner 只读账号。连接 URL 不得进入 API、模型 Prompt、日志、LangSmith 或审计。

Dataset 是否启用、隐私等级、白名单视图、关系和同义词由平台表
`nl2sql_datasets` 管理；应用启动时读取。`NL2SQL_ENABLED` 是全局总开关，不再为每个
Dataset 设置 Python/环境变量开关。连接凭据仍只保存在
`NL2SQL_DATABASE_URLS_JSON`，平台表只保存 `database_key`。

部署顺序：

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\scripts\nl2sql\Initialize-Nl2SqlTestDatabases.ps1
```

生产环境必须替换初始化脚本中的测试密码，并通过密钥管理系统注入连接映射。

## 2. RBAC 与 Dataset Grant

功能权限为 `data:query:execute`，内置角色为 `data_analyst`。`system_admin` 和 `data_analyst` 获得该功能权限，但功能权限不等于 Dataset 访问权。

Dataset Grant 表：

```text
nl2sql_dataset_grants(
  dataset_id,
  subject_type,
  subject_key,
  scope_id,
  enabled,
  expires_at,
  created_by,
  created_at
)
```

`subject_type` 支持 `user、role、department`，三类授权取并集。`scope_id="*"` 表示整个 Dataset。客户端、Router 和 SQL 模型都不能提交 Scope；服务端从当前 RBAC 快照和 Grant 解析，再通过事务级 `set_config` 交给 RLS。

每次查询恢复/确认都重新鉴权。`system_admin` 可得到全 Dataset Scope，但仍受分析视图白名单、SQL AST、只读事务、LIMIT 和超时限制。

开发环境给已有员工账号分配最小 NL2SQL 权限时，先确保该账号存在，再执行幂等脚本：

```powershell
$env:PYTHONPATH = "src"

.\.venv\Scripts\python.exe scripts\nl2sql\grant_employee_dataset_access.py `
  --username "nl2sql_game_employee" `
  --dataset-id "game_test" `
  --scope-id "game_p1" `
  --created-by "local_admin"
```

脚本完成两项持久化操作：

1. 若员工还没有 `data_analyst`，向 `user_roles` 增加该全局角色，使账号获得 `data:query:execute`。
2. 向 `nl2sql_dataset_grants` 增加直接用户 Grant，使该员工只能得到指定的 Dataset Scope。

生产环境不应开放数据库脚本给普通用户；应由后续专用管理员 API 和 React 权限页面完成同样的受控写入与审计。

## 3. HTTP API

### 查询当前用户可访问的 Dataset

```http
GET /nl2sql/datasets
Authorization: Bearer <token>
```

仅返回当前用户可访问项：

```json
{
  "datasets": [
    {
      "dataset_id": "game_test",
      "name": "游戏资产测试数据",
      "domain": "game",
      "privacy_classification": "non_sensitive",
      "report_supported": true
    }
  ]
}
```

### 直接查询

```powershell
$body = @{
    dataset_id = "game_test"
    question = "统计每个项目的资产总费用"
    max_rows = 200
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/nl2sql/query" `
    -Headers @{ Authorization = "Bearer $token" } `
    -ContentType "application/json; charset=utf-8" `
    -Body $body
```

响应包含：

```text
query_id、request_id、trace_id、dataset_id、parameterized_sql、
columns、rows、row_count、truncated、execution_ms、attempt_count、
summary、warnings
```

响应中的 SQL 只包含参数占位符，不返回连接信息。`Decimal` 序列化为字符串，时间使用 ISO 8601。

### RAG 查询与报告

`POST /rag/chat` 和 `POST /rag/chat/stream/events` 增加：

```json
{
  "query": "结合设计文档和资产库生成资产选型报告",
  "dataset_id": "game_test",
  "nl2sql_action": "report"
}
```

规则：

- 未提供 `dataset_id` 时，`nl2sql_action` 必须为空，现有 RAG 行为不变。
- 提供 `dataset_id` 时必须显式提供 `query` 或 `report`。
- `query` 在外部 Router 前确定性进入 `structured_data_query`。
- 游戏 `report` 进入现有 agentic 文档链路。
- 房地产 `report` 在任何外部模型、SQL 或 TaskPlan 创建前返回 `NL2SQL_SENSITIVE_REPORT_FORBIDDEN`。
- deprecated `POST /rag/chat/stream` 携带 Dataset 时返回 `NL2SQL_LEGACY_STREAM_UNSUPPORTED`。

结构化 SSE 查询事件：

```text
nl2sql_sql_generated
nl2sql_result
done
```

报告沿用现有文档进度事件。NL2SQL Tool 事件只发送 `query_id、row_count、status`，不发送完整结果行。

PowerShell SSE 示例：

```powershell
$body = @{
    query = "列出星港远征费用最高的资产"
    dataset_id = "game_test"
    nl2sql_action = "query"
} | ConvertTo-Json -Compress
$curlBody = $body.Replace('"', '\"')

curl.exe -N `
    -X POST "http://127.0.0.1:8000/rag/chat/stream/events" `
    -H "Content-Type: application/json; charset=utf-8" `
    -H ("Authorization: Bearer {0}" -f $token) `
    --data-raw "$curlBody"
```

## 4. SQL 安全与隐私边界

- 只允许单条 `SELECT`、CTE、JOIN、子查询、聚合、窗口函数和集合操作。
- 拒绝 DML、DDL、COPY、CALL、DO、SET、事务命令、系统 Catalog、非白名单对象、`SELECT *` 和危险函数。
- 缺少 LIMIT 时注入 `max_rows+1`，默认 200，硬上限 500。
- 执行事务为只读，`statement_timeout=8s`、`lock_timeout=1s`，并设置受限 `search_path`。
- 只对语法、未知列和类型错误调用模型修复一次；安全、权限、超时和越权错误不修复。
- 审计保存标记化问题、参数化 SQL、SQL hash、状态、耗时和行数，不保存真实参数或结果行。

房地产模型只接收逻辑 Schema、COMMENT 和类型化占位符。真实实体、数字和结果行只在后端内存与数据库连接内出现。房地产结论由受限本地模板回填，禁止外部模型报告。

游戏数据可在行数限制内交给外部模型总结。报告 Researcher 可使用真实检索、`nl2sql_query` 和 Calculator；Writer/Reviewer 不能访问数据库。

## 5. 验证

数据库和代码测试：

```powershell
$env:PYTHONPATH = "src"
.\scripts\nl2sql\Test-Nl2SqlDatabases.ps1
.\.venv\Scripts\python.exe scripts\nl2sql\test_nl2sql_module.py
.\.venv\Scripts\python.exe scripts\nl2sql\test_dataset_authorization.py
.\.venv\Scripts\python.exe scripts\nl2sql\test_nl2sql_rag_routing.py
.\.venv\Scripts\python.exe scripts\nl2sql\test_nl2sql_api_contract.py
```

真实模型基准：

```powershell
.\.venv\Scripts\python.exe scripts\nl2sql\benchmark_real_questions.py --domain game
.\.venv\Scripts\python.exe scripts\nl2sql\benchmark_real_questions.py --domain real_estate
```

浏览器验收可打开 `scripts/phase_15/rag_agent_manual_acceptance.html`，在现有 RAG 表单中选择 `NL2SQL Dataset` 和 `NL2SQL action`。该页面覆盖非流查询、structured SSE、TaskPlan 读取和人工确认；不使用 deprecated `/rag/chat/stream` 承载 NL2SQL。

完整过程、请求/查询/TaskPlan ID、结果和未完成项见 `scripts/docs/NL2SQL测试过程与问题记录.md`。

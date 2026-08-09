# NL2SQL 测试过程与问题记录

## 1. 测试范围与结论

记录日期：2026-07-29。员工 Dataset 权限复测日期：2026-07-30。

本轮实现并验证了自由 NL2SQL 的核心查询链路、RBAC/Dataset Grant、PostgreSQL RLS、房地产敏感标记化、游戏数据查询、API/SSE 契约，以及 Deep Document Researcher 的 `knowledge_retrieval + nl2sql_query + calculator` 工具绑定。

当前结论：

- 房地产真实模型 20 问：可执行 19/20（95%），结果正确 19/20（95%）。
- 游戏真实模型 20 问：可执行 20/20（100%），严格结果正确 17/20（85%）。
- SQL 写操作、系统对象、跨 Dataset、伪造 Scope 和无 Scope 查询由 AST、连接权限及 RLS 三层阻断；自动化攻击用例阻断率 100%。
- 游戏权限已使用非管理员员工账号真实复测：`game_test/game_p1` 返回 2 行，未授权 `game_p2` 返回 0 行；不再使用 `system_admin` 查询结果作为 Dataset Grant 验收依据。
- 房地产最近一次验收的审计字段中，哨兵楼盘名和价格泄露数为 0；审计不保存参数值和结果行。
- 房地产 `report` 在 Router、TaskPlan、SQL 和任何外部报告模型调用前返回 `NL2SQL_SENSITIVE_REPORT_FORBIDDEN`。
- 游戏报告已通过 Web 页面和 structured SSE 完成真实检索、NL2SQL、Calculator、Writer/Reviewer、人工确认、GitLab 分支、Commit、MR 合并、Webhook、Worker 和 ES/Milvus 发布；发布版本为 6，报告已可从 ES 和 Milvus 重新检索。

## 2. 环境与版本

- 操作系统：Windows，PowerShell。
- Python：项目 `.venv`。
- PostgreSQL：16.14。
- 平台主库：`python_agent_study`。
- 房地产测试库：`nl2sql_real_estate_test`。
- 游戏测试库：`nl2sql_game_test`。
- SQL AST：`sqlglot==30.13.0`。
- SQL 模型：项目 `.env` 配置的真实外部模型，本轮为 `qwen3.7-plus`。
- 业务数据库：真实 PostgreSQL 表、分析视图、COMMENT、只读账号和 RLS；未使用 Mock DB、SQLite 或内存仓储。

连接 URL 仅通过 `NL2SQL_DATABASE_URLS_JSON` 注入，本文不记录密码。

## 3. 数据库初始化与种子版本

执行：

```powershell
.\scripts\nl2sql\Initialize-Nl2SqlTestDatabases.ps1
```

脚本可重复执行，实际创建：

- 房地产：3 个楼盘、6 栋楼、6 类户型、72 套房源。
- 游戏：3 个项目、45 个资产。
- 每库 2 个可 JOIN 的 `analytics` 视图。
- 基础业务表启用并强制 RLS，分析视图使用 `security_invoker=true`。
- 只读账号不是 owner、没有 `SUPERUSER` 或 `BYPASSRLS`。
- 游戏库 CHECK 约束保证只有 `3D模型` 资产的 `polygon_count` 非空。

验证：

```powershell
$env:PYTHONPATH = "src"
$env:NL2SQL_DATABASE_URLS_JSON = Get-Content Env:NL2SQL_DATABASE_URLS_JSON
.\.venv\Scripts\python.exe scripts\tests\nl2sql\test_real_databases.py
```

结果：`NL2SQL real database checks passed`。覆盖无 Scope 零行、不同用户连接池 Scope 不串线、跨项目隔离、COMMENT、角色属性、DDL 拒绝和 `business` Schema 直接访问拒绝。

## 4. 自动化测试步骤与结果

```powershell
$env:PYTHONPATH = "src"

.\.venv\Scripts\python.exe scripts\tests\nl2sql\test_nl2sql_module.py
.\.venv\Scripts\python.exe scripts\tests\nl2sql\test_dataset_authorization.py
.\.venv\Scripts\python.exe scripts\tests\nl2sql\test_nl2sql_rag_routing.py
.\.venv\Scripts\python.exe scripts\tests\nl2sql\test_nl2sql_api_contract.py
.\.venv\Scripts\python.exe scripts\tests\agent_research\test_schema_field_descriptions.py
.\.venv\Scripts\python.exe scripts\tests\integrations\test_langsmith_tracing.py
.\.venv\Scripts\python.exe scripts\tests\agent_research\test_agent_task_router.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agent_task_planning_flow.py
.\.venv\Scripts\python.exe scripts\tests\document_security\test_deep_document_agent_workflow.py
.\.venv\Scripts\python.exe -m compileall -q src\fast_app scripts\nl2sql
```

全部通过。`test_agent_task_planning_flow.py` 在受限网络中输出 LangSmith 连接警告，但本地断言通过；没有把 SQL、参数、结果行或房地产原始问题写入自定义 trace。

权限矩阵覆盖：

- 有 `data:query:execute` 但无 Dataset Grant。
- 有 Grant 但无功能权限。
- 用户、角色、部门 Grant 并集。
- `system_admin` 的全 Dataset Scope。
- 跨 Dataset、跨项目和客户端伪造 Scope。
- 缺少事务 Scope 默认零行。
- 连接池连续服务两个用户时 Scope 不串线。

## 5. 真实模型与真实 PostgreSQL 查询验收

执行：

```powershell
$env:PYTHONPATH = "src"
$env:NL2SQL_DATABASE_URLS_JSON = "<由部署环境注入的 JSON>"

.\.venv\Scripts\python.exe scripts\nl2sql\accept_real_model_queries.py
.\.venv\Scripts\python.exe scripts\nl2sql\benchmark_real_questions.py --domain game
.\.venv\Scripts\python.exe scripts\nl2sql\benchmark_real_questions.py --domain real_estate
```

代表性真实查询：

- 游戏 `query_id=d85a967a-0a76-450a-8a5f-e15e289f2949`，返回 2 行，首次 SQL 即执行成功。
- 房地产 `query_id=06e73034-86bb-4de5-92fb-e4452a73771f`，返回 12 行，首次 SQL 即执行成功。

20 问基准：

| Dataset | 可执行率 | 严格正确率 | 结论 |
|---|---:|---:|---|
| `game_test` | 20/20，100% | 17/20，85% | 达标 |
| `real_estate_test` | 19/20，95% | 19/20，95% | 达标 |

游戏 3 个严格差异：

- `query_id=19a06bef-5949-4c6e-8d48-253246fe9bd9`：模型把中文项目名用于 `project_id`，返回 0 行，属于真实错误。
- `query_id=6f08a3c5-13f4-41e2-83f7-b73563f84ca9`：模型额外返回 `project_id`，行数和统计值正确，但列集合不完全等于基准。
- `query_id=01c8545f-ae06-42d7-8b84-ff15a728884b`：模型额外返回 `project_id`，行数和统计值正确，但列集合不完全等于基准。

房地产唯一不可执行问题是“统计三个楼盘的房源总数”，属于单次模型 SQL 执行错误。没有为基准问题增加关键词特判。

## 6. 房地产隐私验证

房地产链路使用带字段语义但不可还原的请求级占位符，例如：

```text
__PROJECT_NAME_1__
__INVENTORY_STATUS_1__
__ORIENTATION_1__
__ROOM_COUNT_1__
__NUMBER_1__
```

真实值仅保存在请求内存 Vault，模型返回参数引用后由后端绑定。执行结果只进入本地安全模板回填，不返回外部总结模型。

验证：

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\nl2sql\check_latest_privacy_audit.py
```

结果：

- `name_in_question=False`
- `price_in_question=False`
- `name_in_sql=False`
- `price_in_sql=False`

开发早期曾因普通数值未正确标记化，生成 1 条包含合成哨兵值的测试审计。定位后先修复根因，再按精确 Dataset 和哨兵条件删除该测试审计；删除数量为 1，不能恢复。生产数据未受影响。

## 7. 游戏报告链路状态

代码级与自动化验证已完成：

- Dataset 报告固定进入现有 `knowledge_document_management` 和 agentic Deep Document 链路。
- Researcher 的 `nl2sql_query` 由服务端闭包绑定 Dataset，Tool 参数不含 `dataset_id`。
- Researcher 同时复用现有 `knowledge_retrieval` 和 `calculator`。
- 未实际使用这三个 Tool 时，交付物在 Writer 前失败。
- NL2SQL Tool 进度事件只包含 `query_id、row_count、status`。
- Writer/Reviewer 没有数据库 Tool。
- 最终报告必须保留后端 Markdown 表格与 `query_id`。

真实浏览器验收已完成发布后半流程：

1. API 运行时的 GitLab 凭据可用，TaskPlan 确认后成功创建分支、Commit 和 MR；早期种子辅助脚本只读取到空值，不能代表服务运行时的最终凭据状态。
2. 当前知识库可检索到真实游戏资产 Excel，但没有命中用户指定的《星港远征》设计说明；Researcher 没有伪造证据，而是在报告中明确提示该限制。
3. 创建部门匹配账号 `product-planning-maintainer-e2e`，只授予 `rag-product-planning-docs` 项目直接 Maintainer，不加入顶层 Group；该账号批准并合并 MR。
4. 合并后的 Push Hook 返回 HTTP 202；Worker 从 GitLab 读取报告，调用真实 DashScope Embedding，并发布到 PostgreSQL、ES 和 Milvus。
5. PostgreSQL 同步任务 `gitlab_job_d1aaac1d2fa7474cb40dbc248321fc96` 为 `succeeded/published`，知识发布版本为 6。
6. ES 按报告标题命中 2 条记录；Milvus 按报告 `doc_id` 命中 14 个有效 Chunk，全部为 `valid_from_version=6、valid_to_version=0`。

## 8. Web 手工验收记录

验收页面：`scripts/phase_15/rag_agent_manual_acceptance.html`。本轮为该页面增加 `NL2SQL Dataset` 和 `NL2SQL action` 控件，请求仍复用页面原有的 `/rag/chat`、`/rag/chat/stream/events`、TaskPlan 读取和确认操作，没有创建另一套测试 UI。

测试环境：

- 静态页面：`http://127.0.0.1:5173/rag_agent_manual_acceptance.html`。
- FastAPI：`http://127.0.0.1:8000`。
- 2026-07-30 权限复测登录用户：普通员工 `nl2sql_game_employee`，只有全局角色 `data_analyst`、功能权限 `data:query:execute`、主部门 `product_planning` 和直接用户 Grant `game_test/game_p1`，没有 `system_admin`。
- 2026-07-30 权限复测数据源：真实 PostgreSQL 和真实外部 SQL 模型；没有启动 GitLab 容器，没有执行报告或文档创建链路。
- 2026-07-29 的旧查询、房地产隐私和报告记录使用过系统管理员账号。管理员会直接得到全 Dataset Scope，因此旧结果只保留为功能、隐私或文档链路证据，不能作为普通员工 Dataset Grant 的权限证据。

### 8.1 游戏员工账号授权项目查询

- 输入：查询《星港远征》中已授权的 3D 模型资产，要求返回名称、费用、模型面数、类别和使用场景。
- 设置：`dataset_id=game_test`、`nl2sql_action=query`、`allow_web_fallback=false`。
- 员工 `/auth/me`：`global_role_codes=["data_analyst"]`、`global_permission_codes=["data:query:execute"]`、`department_codes=["product_planning"]`。
- 持久化 Grant：`dataset_id=game_test`、`subject_type=user`、`subject_key=<该员工 users.id>`、`scope_id=game_p1`、`enabled=true`。
- `request_id/trace_id=e6addff93a2441f88982752e8b32581a`。
- `query_id=dc6aabb8-acdd-4c2a-87f7-20d51b6cc456`。
- 结果：首次 SQL 执行成功，返回 2 行：`角色资产01 / 1075 / 9200`、`角色资产06 / 2450 / 15200`；返回 Markdown 表格，未调用 WebSearch，没有 TaskPlan。
- 数据库审计：`status=completed`、`row_count=2`，审计 `user_id` 与该员工账号一致。
- 结论：普通员工的功能权限和 `game_p1` 直接用户 Grant 生效。

复测第一次启动的 FastAPI 进程运行在受限网络沙箱中，外部 SQL 模型连接触发
`APIConnectionError`，页面显示 `Failed to fetch`。改为允许外部模型网络连接并关闭本轮
不需要的 LangSmith tracing 后，同一员工、同一页面和同一问题复测通过；该失败发生在 SQL
生成阶段，不是权限拒绝或数据库执行错误。

### 8.1.1 游戏员工账号未授权项目查询

- 输入：查询《山海旅人》的全部游戏资产，返回资产名称和费用。
- 已知范围：`山海旅人=game_p2`，员工只拥有 `game_p1`。
- 设置：`dataset_id=game_test`、`nl2sql_action=query`、`allow_web_fallback=false`。
- `request_id/trace_id=8f9be8d9eb5342f285a8222c516e3821`。
- `query_id=88214182-fd38-41fc-8168-97b47d0bc8ad`。
- 模型生成的参数化 SQL 正常通过策略校验，查询 `analytics.asset_catalog` 并按项目名称过滤。
- 结果：`row_count=0`、`rows=[]`、Markdown 表格为 `_查询无结果_`，总结为“未查询到《山海旅人》的游戏资产。”
- 数据库审计：`status=completed`、`row_count=0`。这说明请求和 SQL 均合法，但 PostgreSQL RLS 将 `game_p2` 数据过滤，而不是应用伪造一个权限错误。
- 结论：员工不能读取 Grant 之外的游戏项目，Scope 隔离通过。

### 8.2 房地产敏感查询

- 输入：查询“云栖雅苑”总价低于 250 万且可售的房源，返回楼栋、户型、面积和价格。
- 设置：`dataset_id=real_estate_test`、`nl2sql_action=query`。
- `request_id/trace_id=bdaaea4db6454fae8ebc616e4b19c398`。
- `query_id=569c7063-54f8-434d-871a-1a35eaee7e4f`。
- 结果：首次 SQL 执行成功，返回 12 行；响应 SQL 为参数化 SQL，本地生成“查询返回 12 行结果”总结。
- 隐私复核：审计总数为 62；最新审计的楼盘名、价格在标记化问题和参数化 SQL 中均未出现。
- 结论：查询正确，“标记化/伪名化 + 回填”通过。

### 8.3 房地产报告阻断

- 设置：`dataset_id=real_estate_test`、`nl2sql_action=report`。
- `request_id/trace_id=53f6953f181d4cefb1f3b4de34746574`。
- 结果：HTTP 403，错误码 `NL2SQL_SENSITIVE_REPORT_FORBIDDEN`；页面没有 TaskPlan。
- 旁证：执行前后房地产审计总数均为 62，证明未执行 SQL。
- 结论：通过。

### 8.4 游戏联网报告

第一次报告 `task_plan_id=task_plan_20260729115704_6273391d7a58` 在 `change_set_validation` 失败。根因是旧测试管理员没有主部门，创建文档的目标路径被回退到用户目录，无法唯一定位 GitLab Project。测试账号脚本补充 `product_planning` 主部门和部门文档管理员角色后，使用新 TaskPlan 复测。

复测记录：

- `request_id/trace_id=0c2fe08005d14b31a02ca682f2f925e0`。
- `task_plan_id=task_plan_20260729120333_0a194ffc5a82`。
- `query_id=36b32d98-a286-4988-bb34-9271774382fe`，返回 5 行。
- `used_tools=["calculator","knowledge_retrieval","nl2sql_query"]`。
- Calculator：平均费用 `6025` 元；最高与最低费用差 `11000` 元，和人工基准一致。
- Writer 生成的报告包含 NL2SQL Markdown 表格、成本统计和 `query_id`；Reviewer 通过，置信度 `0.95`。
- 人工点击页面“确认并执行 TaskPlan”后，创建分支 `agent/task_plan_20260729120333_0a194ffc5a82-d12c8509`、Commit `36fa9ea144c70781aaab3b7d9295e092f1ffca33` 和 GitLab MR `!1`。
- MR：`http://localhost:8929/rag-kb-dev/rag-product-planning-docs/-/merge_requests/1`。
- 新建部门匹配账号 `product-planning-maintainer-e2e`，只作为该 Project 的直接 Maintainer；该账号批准并合并 MR。
- MR 最终状态为 `merged`，合并提交 `fbd7050fa0106af7d4ff5b3bff8088f1af9da0a3`，源分支已删除。
- 合并后的 Push Hook 返回 HTTP 202，数据库中的 Change Request 状态同步为 `merged`。
- 第一次 Worker 发布因受限进程无法连接真实 DashScope Embedding 而失败；在用户明确同意将非敏感游戏报告发送给 DashScope 后，重放 Push Hook 并在允许联网的 Worker 中复测成功。
- 成功同步任务：`gitlab_job_d1aaac1d2fa7474cb40dbc248321fc96`，状态 `succeeded`，阶段 `published`，发布版本 6。
- PostgreSQL 的报告 `doc_id=d7531fc88968ce8f715424063b97499204a409ba01d0ede25d4a1d6b8b5d36b3` 状态为 `active`，`source_revision` 与合并提交一致。
- ES 按“星港远征资产选型报告”命中 2 条；Milvus 按该 `doc_id` 命中 14 个有效 Chunk，版本边界均为 `valid_from_version=6、valid_to_version=0`。
- TaskPlan 状态仍为 `completed_with_warnings`，其 warning 来自报告研究阶段未精确命中指定设计说明，不影响后续 MR 合并和知识发布成功。
- structured SSE 在 Deep Document 长任务期间较长时间没有可见增量，随后集中收到 Researcher、NL2SQL、Writer、Reviewer、待确认和完成事件；需要作为前端体验问题继续观察。

结论：MR 合并、Webhook、Worker、PostgreSQL、ES/Milvus 发布和发布后重新检索均通过；唯一保留项是研究阶段未精确命中《星港远征》设计说明，报告已如实披露该限制。

## 9. Bug 与修复记录

| Bug | 根因 | 修复 | 回归结果 |
|---|---|---|---|
| 合法 `AND` 被拒绝 | SQLGlot 将部分内建表达式表示为 `Func` | 仅对 `Anonymous` 函数执行严格白名单，并保留显式危险函数拒绝 | SQL Policy 通过 |
| 房地产库存状态未标记化 | 实体目录只覆盖楼盘和数字 | 将库存、朝向、房间数纳入本地实体目录 | 哨兵泄露 0 |
| 中文相邻数字未被识别 | Python `\w` 包含中文 | 数字边界只排除 ASCII 标识符和小数点 | 价格参数正确绑定 |
| 通用占位符绑定到错误字段 | `__ENTITY_N__` 不携带最小字段语义 | 改为不可还原的类型化占位符 | 房地产正确率由 30% 提升至 95% |
| 参数化 LIMIT 被策略误拒 | AST LIMIT 为参数节点 | 只接受正整数 LIMIT 参数并在后端夹紧到上限 | 回归通过 |
| `security_invoker` 视图需要底表权限 | 只读角色缺少执行视图所需 SELECT | 授予底表 SELECT，同时撤销 `business` Schema USAGE | 视图可查、底表不可直接解析 |
| 业务连接可能误指向平台主库 | 仅固定 Dataset ID 不能防止 URL 配错 | `DatasetRegistry` 比较主库名并在启动时拒绝 | 模块回归通过 |
| 未授权楼盘名可能绕过标记化 | 实体目录曾按用户 Scope 读取，跨 Scope 实体无法识别 | 本地标记化目录读取全量实体，真实 SQL 执行仍使用用户 Scope | 跨 Scope 哨兵回归通过 |
| 方案文档包含两份 Plan | 修订方案追加在旧方案末尾 | 修订版移到顶部，移除旧 Plan 和临时修改块 | 文档结构已统一 |
| Web 验收页无法提交 NL2SQL 请求 | 页面没有 Dataset 和 action 控件 | 在现有请求体中按选择条件加入 `dataset_id` 和 `nl2sql_action` | query/report 均通过页面发起 |
| 使用 `system_admin` 作为 Dataset Grant 权限验收账号 | 管理员分支直接返回 `scope_ids=("*",)`，不会读取 Grant 表，无法证明员工授权关系 | 创建普通员工 `nl2sql_game_employee`，赋予 `data_analyst` 和直接用户 Grant `game_test/game_p1`；页面分别查询授权 `game_p1` 与未授权 `game_p2` | 授权项目 2 行、未授权项目 0 行，审计均为 `completed` |
| 报告测试账号无法定位文档 Project | 系统管理员测试账号没有主部门 | 给测试管理员绑定 `product_planning` 主部门和部门文档管理员角色 | 新 TaskPlan 成功创建 MR |
| 合并后首次发布无法生成 Embedding | Worker 运行在受限网络环境，无法连接 DashScope | 用户确认非敏感报告可外发后，在允许联网的真实 Worker 中重放同一 Push Hook | 同步任务 `succeeded/published`，ES/Milvus 可检索 |
| NL2SQL LangSmith 事件使用默认名称 | structured output 外层和底层模型没有业务 `run_name/name` | SQL 生成按 Domain 命名 chain/model，游戏结果总结单独命名 | 真实游戏和房地产查询均只出现 `nl2sql.*` 业务名称 |

后续需要观察：游戏模型偶发把中文名称用于 `*_id`。当前正确率已达到 85% 门槛；若线上评测持续出现，应优先补强 Schema COMMENT/生成提示或做类型一致性校验，不应添加问题关键词路由。

## 10. 2026-07-31 至 2026-08-01 Dataset Router 改造与 Web 复测

### 10.1 环境与权限

- 平台主库 Alembic 已从 `20260729_0011` 升级到 `20260731_0012`。
- 新增 `nl2sql_datasets`，当前有 `game_test/non_sensitive` 与
  `real_estate_test/sensitive` 两条启用记录。
- `DatasetRegistry.refresh()` 在 FastAPI 启动时从平台表加载定义；业务库 URL 仍只从
  部署环境读取。
- 游戏验收使用普通员工 `nl2sql_game_router_employee`：
  `data_analyst + product_planning + game_test/game_p1`，没有 `system_admin`。
- 房地产验收使用普通员工 `nl2sql_real_estate_employee`：
  `data_analyst + product_planning + real_estate_test/re_p1`，没有 `system_admin`。
- PostgreSQL、Redis、Elasticsearch、Milvus 均使用本地真实服务；GitLab 容器未启动，
  本轮不测试文档创建、MR、Webhook 或 Worker。
- Web 页面仍为
  `scripts/phase_15/rag_agent_manual_acceptance.html`，没有用 API 脚本替代页面验收。

### 10.2 计划中的四个场景

| 场景 | 预期 route intent | 当前状态 |
|---|---|---|
| 敏感房地产 Dataset 查询 | API 规则直达 `structured_data_query` | 已通过，首个业务事件为 `nl2sql_sql_generated` |
| 非敏感游戏单一数据库问题 | `structured_data_query`，`source=model` | 已通过 |
| 非敏感游戏离线简单知识库问题 | `simple_rag` | 已通过，真实 ES/Milvus 有检索结果 |
| 非敏感游戏联网复杂知识库问题 | `question_decomposition` | 已通过，生成分析型 TaskPlan 后停止 |

### 10.3 已通过：游戏单一数据库问题

- 页面输入：查询《星港远征》中已授权的 3D 模型资产名称、费用、模型面数、类别和使用
  场景，按费用从高到低排序。
- 控件：`dataset_id=game_test`、`nl2sql_action=query`、
  `allow_web_fallback=false`。
- `/auth/me`：`global_role_codes=["data_analyst"]`、
  `global_permission_codes=["data:query:execute"]`、
  `department_codes=["product_planning"]`。
- 第一次请求 `request_id=e1474382fade4dfe89bae83398ff7295` 失败。根因是
  `AgentResearchPolicy.nl2sql_action` 仍只接受 `report`，非敏感 query 进入 Router 时
  无法把 `query` 保存到研究策略。修复为 `Literal["query", "report"]` 后重启服务重跑。
- 成功请求 `request_id/trace_id=ec5b88ca9df942308470ffb49be2c626`。
- `query_id=178a56e0-b724-4063-b379-25a3e3f3b888`。
- 页面先收到：

```json
{
  "event": "agent_route_selected",
  "data": {
    "intent": "structured_data_query",
    "source": "model",
    "confidence": 1,
    "reason": "router_selected_structured_data_query"
  }
}
```

- 随后收到 `nl2sql_sql_generated` 与 `nl2sql_result`；SQL 首次执行成功，返回 2 行：
  `角色资产06 / 2450 / 15200`、`角色资产01 / 1075 / 9200`。
- 结论：非敏感 Dataset query 已进入现有 Router，由模型返回
  `structured_data_query`，不是 API 硬编码直达。

### 10.4 已通过：游戏离线简单知识库问题

- 2026-08-01 用户解除内置浏览器的本地端口限制后，继续使用同一 Web 验收页复测。
- 页面输入：知识库中的《星港远征资产选型报告》推荐了哪些资产？
- 控件：`dataset_id=game_test`、`nl2sql_action=query`、
  `allow_web_fallback=false`。
- 第一次请求因 FastAPI 进程处于禁止外部模型联网的沙箱中，页面返回
  `clarification_required/router_unavailable`。该结果不记为业务通过；将本地 FastAPI
  验收进程重启到允许访问真实外部模型的环境后，使用新 session 重新提交。
- 成功请求 `request_id/trace_id=ec4941e52b41487e8d012854081c051b`。
- 页面事件：`intent=simple_rag`、`source=model`、`confidence=0.95`、
  `reason=default_retrieve`。
- `sources` 包含真实 Elasticsearch 和 Milvus 结果，命中文档
  `星港远征资产选型报告.md`，知识版本为 6。
- 页面没有出现 `nl2sql_sql_generated`、`nl2sql_result` 或 WebSearch 事件。

结论：绑定非敏感 Dataset 不等于强制查询数据库。只需要知识库事实时，Router 会让请求
继续进入原有 `simple_rag` 链路。

### 10.5 已通过：游戏联网复杂知识库问题

- 页面输入：联网查询公开的移动端 3D 资产性能优化建议，并结合知识库中的
  《星港远征资产选型报告》，分步骤分析移动端适配性以及仍需核实的费用和模型面数。
- 控件：`dataset_id=game_test`、`nl2sql_action=query`、
  `allow_web_fallback=true`。
- 成功请求 `request_id/trace_id=453f40b6cbda460cadfddce3742cafea`。
- 页面事件：`intent=question_decomposition`、`source=model`、`confidence=1`、
  `reason=agent_task_plan_detected`。
- 创建分析型 TaskPlan：`task_plan_id=task_plan_20260801075732_b268f35a6b18`。
- TaskPlan 的服务端研究策略保存了
  `dataset_id=game_test、nl2sql_action=query、web_policy=fallback`；Planner 生成 5 个
  子问题，分别覆盖公开资料、知识库、综合判断、费用核实和模型面数核实。
- 页面最终进入 `waiting_confirmation`。本轮只验收检索路由，因此没有点击确认，没有执行
  子问题，也没有访问 GitLab。

结论：`allow_web_fallback=true` 只是后续 Research Worker 的工具许可，不会把顶层路由
硬改为 `web_research`。需要多个来源和多个步骤时，Router 正确选择
`question_decomposition`。

### 10.6 已通过：房地产敏感 Dataset 查询

- 页面使用普通员工 `nl2sql_real_estate_employee`，`/auth/me` 显示
  `data_analyst`、`data:query:execute` 和 `product_planning`，没有 `system_admin`。
- 页面输入：查询“云栖雅苑”总价低于 250 万元且可售的房源，返回楼栋、户型、面积和
  价格。
- 控件：`dataset_id=real_estate_test`、`nl2sql_action=query`、
  `allow_web_fallback=false`。
- 第一次真实请求 `query_id=848ee6a4-d6b8-4f96-8815-91bfbd87d4de` 返回 0 行。排查发现
  员工 Dataset Grant 错写为 `real_p1`，而业务库真实项目 ID 是 `re_p1`。RLS 因 Scope
  不匹配而正确过滤为零行。
- 修正唯一一条员工 Grant 后，从同一 Web 页面使用新 session 重跑。
- 成功请求 `request_id/trace_id=f09ee65f891f40d28b2b179f266a4f13`，
  `query_id=9258c606-4c71-437c-bdaa-00406362ae2a`。
- 页面首个业务事件就是 `nl2sql_sql_generated`，没有 `agent_route_selected`；这说明敏感
  问题没有进入普通 Router。
- 参数化 SQL 首次执行成功，返回 `1号楼/2号楼` 共 12 套可售房源，价格全部低于
  250 万元，结果与测试数据基准一致。

结论：敏感 Dataset 仍由 API 的隐私规则在 Router 前直达标记化 NL2SQL；功能权限、
Dataset Grant 和 PostgreSQL RLS 都实际参与了查询。

### 10.7 本轮 Bug 与修复

| Bug | 根因 | 修复 | Web 回归结果 |
|---|---|---|---|
| 简单知识库请求返回 `router_unavailable` | FastAPI 验收进程无法连接真实 Router 模型 | 在明确授权后只重启本地 FastAPI 到可联网环境 | 同一页面重跑返回 `simple_rag` |
| 房地产查询返回 0 行 | 员工 Grant 使用不存在的 `real_p1`，真实业务 Scope 是 `re_p1` | 修正该员工唯一一条 Dataset Grant | 同一页面重跑返回 12 行 |

四个场景最终都由 `scripts/phase_15/rag_agent_manual_acceptance.html` 发起并读取结构化
SSE；模块脚本和服务日志仅用于失败诊断，没有替代 Web 验收。GitLab 容器没有启动，
本轮没有测试文档创建、MR、Webhook 或 Worker。

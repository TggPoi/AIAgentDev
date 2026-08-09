# Python Agent Study

面向企业知识场景的 Python / FastAPI / LangGraph RAG Agent 后端企业级项目。

项目已从基础混合检索演进为一套可评测、可观察、可授权、可人工确认的 Agent 后端：统一聊天入口可以在普通 RAG、复杂 Research、知识文档管理、公开 Web 检索和受控 NL2SQL 之间进行结构化路由，并通过 JSON / SSE 向后续 React 前端返回稳定状态。

> 当前仓库只包含后端。React Web 前端是接口设计的目标消费者，尚未包含在本仓库中。

## 当前能力

| 能力 | 当前实现 |
| --- | --- |
| RAG | Milvus 向量检索、Elasticsearch 关键词检索、RRF、rerank、来源与多阶段分数 |
| LangGraph | `classic`、`langgraph`、`rag_agent` 三个 provider；显式 Graph 是 Agent 主线 |
| 结构化路由 | `simple_rag`、`question_decomposition`、`knowledge_document_management`、`web_research`、`structured_data_query`、`clarification_required` |
| Agentic Research | Planner / Reviewer / 确定性 Validator、依赖感知并行 Worker、证据聚合、预算与失败收敛 |
| 文档多 Agent | Coordinator / Researcher / Writer / Reviewer、PostgreSQL checkpoint、人工确认、恢复与取消 |
| 文档与知识库 | Markdown / Text CLI ingestion；PPTX / XLSX 异步导入、父子 Chunk、ACL metadata、版本化发布 |
| Web 检索 | Bocha 搜索、指定站点/URL、正文抓取、重定向约束、Sitemap rescue、多来源结果 |
| NL2SQL | Dataset 绑定、RBAC/Grant、只读 SQL Policy、参数化查询、RLS 与敏感值处理 |
| 认证与授权 | JWT、数据库 API Key、全局/部门 RBAC、知识检索 ACL、Agent Tool 权限与审计 |
| GitLab 文档资产 | Webhook、同步队列、独立 Worker、版本发布、Agent 变更分支与 Merge Request |
| 多轮会话 | Redis 最近窗口、PostgreSQL 消息与摘要、query rewrite、请求级冻结上下文 |
| 安全与观测 | Prompt Guard、请求大小限制、结构化错误、request/trace ID、LangSmith、debug trace |
| 扩展工具 | `knowledge_retrieval`、`web_search`、`calculator`、文档工具、MCP stdio adapter |

多数高风险或外部集成功能默认关闭，必须显式配置后才会启用。代码中“已经实现”不等于本机已经配置好对应的数据库、搜索引擎、GitLab 或模型服务。

## 核心架构

```mermaid
flowchart TD
    A["React / API Client"] --> B["FastAPI API + Middleware"]
    B --> C["Auth / RBAC / Request ID / Prompt Guard"]
    C --> D["POST /rag/chat or /rag/chat/stream/events"]
    D --> E["RagAgentPipeline"]
    E --> F["Frozen conversation and permission snapshot"]
    F --> G["Structured AgentTaskRouter"]

    G --> H["Simple RAG / direct answer"]
    G --> I["Question decomposition"]
    G --> J["Knowledge document management"]
    G --> K["Direct Web research"]
    G --> L["Structured data query"]
    G --> M["Clarification response"]

    H --> N["Milvus + Elasticsearch + RRF + rerank"]
    I --> O["Planner + Reviewer + Validator"]
    O --> P["Parallel Research Workers + synthesis"]
    J --> Q["TaskPlan + human confirmation"]
    Q --> R["Coordinator / Researcher / Writer / Reviewer"]
    K --> S["Search + page fetch + Sitemap rescue"]
    L --> T["NL2SQL Policy + authorized Dataset"]

    N --> U["PostgreSQL / Redis / ES / Milvus"]
    P --> U
    R --> V["Knowledge store or GitLab Merge Request"]
    T --> W["Read-only business database"]
```

关键边界：

- Router 只判断业务意图，不生成可信路径、文档 ID、SQL 权限或 Tool 参数。
- 会话历史只作为当前请求的有界上下文，不是授权事实或未完成任务状态。
- 高风险文档操作先生成 TaskPlan，再由独立确认接口执行；确认时重新检查权限和资源状态。
- Planner / Reviewer 的结构化输出仍需经过服务端 Validator，Prompt 不能代替确定性约束。
- `pipeline.stream_events()` 是结构化流主线；`pipeline.stream()` 只保留兼容 token 流。

## 主要 API

FastAPI 启动后可在 `http://127.0.0.1:8000/docs` 查看当前 OpenAPI。下面只列面向产品主线的入口：

| 方法与路径 | 用途 |
| --- | --- |
| `GET /health` | 服务健康检查 |
| `POST /auth/login` | 用户名/邮箱和密码登录，返回 JWT token pair |
| `POST /auth/refresh` | 刷新 JWT |
| `GET /auth/me` | 当前用户、部门、角色和权限上下文 |
| `POST /auth/api-keys` | 创建数据库持久化 API Key |
| `POST /rag/chat` | 非流式 RAG / Agent 主接口，返回完整答案、sources、request/trace ID |
| `POST /rag/chat/stream/events` | React 主流式接口，返回结构化 SSE 事件 |
| `POST /rag/chat/stream` | 已废弃的 token-only 兼容接口，不承载新功能 |
| `GET /agent/task-plans/{task_plan_id}` | 获取 TaskPlan 结构化状态 |
| `GET /agent/task-plans/{task_plan_id}/markdown` | 获取人工审查视图 |
| `POST /agent/task-plans/{task_plan_id}/confirm` | 确认并执行等待中的高风险计划 |
| `POST /agent/task-plans/{task_plan_id}/confirm/stream` | 确认并以 SSE 返回执行进度 |
| `POST /agent/task-plans/{task_plan_id}/cancel` | 取消任务 |
| `POST /agent/task-plans/{task_plan_id}/retry` | 恢复允许重试的任务 |
| `POST /knowledge-documents/import-jobs` | 创建 PPTX / XLSX 知识导入任务 |
| `GET /knowledge-documents/import-jobs/{job_id}` | 查询导入任务状态 |
| `GET /nl2sql/datasets` | 列出当前用户已授权 Dataset |
| `POST /nl2sql/query` | 对已授权 Dataset 执行受控只读查询 |
| `POST /integrations/gitlab/webhooks/{source_id}` | 接收 GitLab Webhook |
| `GET /knowledge/publication/status` | 获取已发布知识版本 |
| `POST /debug/rag/trace` | 受 token 保护的内部 RAG 调试接口 |

`/chat`、`/rag/search`、`/stream/*`、`/error-demo/*` 等早期学习接口仍保留用于兼容或演示，但不是 React 新功能的设计入口。

## 目录结构

```text
src/fast_app/
  api/                 FastAPI 路由、SSE 与 HTTP 边界
  graph/               LangGraph RAG / Agent 状态、节点和 Graph Builder
  services/
    rag/               RAG、RAG Agent、Web 增强检索与 Prompt Guard
    agent_tasks/       Router、TaskPlan、Research、文档多 Agent
    auth/              JWT、API Key、RBAC 与权限服务
    nl2sql/            Dataset、授权、SQL Policy 与查询服务
    conversation/      Redis/PostgreSQL 会话与 query rewrite
  agents/              Tool、MCP adapter、runtime policy 与 Agent skills
  ingestion/           Loader、父子 Chunk、metadata 与 ES/Milvus 写入
  integrations/gitlab/ GitLab API、Webhook、同步、Worker 与 MR
  evaluation/          RAG 离线评测
  db/                  SQLAlchemy 表、Session 与持久化边界
  core/                Settings、日志、异常、LangSmith 与请求上下文
  schemas/             FastAPI / OpenAPI 公共模型
  domain/              内部领域模型

alembic/               PostgreSQL schema migrations
scripts/tests/         按功能分类的可执行回归脚本
scripts/docs/          实现教程、验收记录与故障复盘
runtime/               本地 TaskPlan 等运行时数据，不是源码
```

## 本地启动

### 1. 前置条件

- Windows PowerShell
- Python 3.12（当前虚拟环境为 Python 3.12.0）
- PostgreSQL：应用启动会读取平台数据库中的 NL2SQL Dataset 配置，因此即使使用 mock 检索也必须可连接
- 可选：Redis、Milvus、Elasticsearch、GitLab、Bocha 和 OpenAI-compatible 模型服务

仓库当前没有提交 Docker Compose 或 `.env.example`。外部服务需要单独启动，敏感配置写入本地 `.env`（该文件已被 `.gitignore` 忽略）或当前 PowerShell 会话。

### 2. 安装依赖

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. 配置最小本地环境

以下配置使用 `classic + mock retriever` 作为最小启动基线。Agent Router 的三个连接字段当前会在应用启动时统一校验，因此即使启动 `classic` provider 也必须填写；调用 `rag_agent` 时必须改为真实可用的模型连接。

```powershell
$env:PYTHONPATH="src"
$env:DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/python_agent_study"

$env:RAG_PIPELINE_PROVIDER="classic"
$env:LLM_PROVIDER="mock"
$env:VECTOR_RETRIEVER_PROVIDER="mock"
$env:KEYWORD_RETRIEVER_PROVIDER="mock"
$env:RERANKER_PROVIDER="none"

$env:AGENT_ROUTER_API_KEY="local-startup-placeholder"
$env:AGENT_ROUTER_BASE_URL="http://127.0.0.1:1/v1"
$env:AGENT_ROUTER_MODEL_NAME="unused-by-classic"
$env:AUTH_ENABLED="false"
```

上面的 Router 占位值只适用于不调用 Router 的 `classic` 启动检查，不代表 Agent 能力可用。

### 4. 初始化数据库

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

### 5. 启动 FastAPI

```powershell
.\.venv\Scripts\uvicorn.exe fast_app.main:app --reload
```

健康检查：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health"
```

如果要运行 Agent 主线，将 `RAG_PIPELINE_PROVIDER` 改为 `rag_agent`，并配置真实的 `AGENT_ROUTER_*`、`OPENAI_API_KEY`、`OPENAI_BASE_URL` 和模型名。启用文档多 Agent 时还必须配置有效的 AES-256 checkpoint 密钥：

```powershell
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$env:LANGGRAPH_AES_KEY_BASE64 = [Convert]::ToBase64String($bytes)
$env:AGENT_DOCUMENT_TOOLS_ENABLED = "true"
```

不要在已有未完成任务的环境中随意更换 `LANGGRAPH_AES_KEY_BASE64`，否则旧 checkpoint 将无法解密恢复。

## 调用主接口

### 非流式请求

普通 JSON API 在 PowerShell 中优先使用 `Invoke-RestMethod`：

```powershell
$body = @{
  session_id = "readme-demo"
  query = "什么是混合检索？"
  mode = "hybrid"
  top_k = 5
  min_score = 0
} | ConvertTo-Json -Compress

$response = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/rag/chat" `
  -ContentType "application/json; charset=utf-8" `
  -Body $body

$response | ConvertTo-Json -Depth 8
```

### 结构化 SSE

Windows PowerShell 调用原生 `curl.exe` 时需要转义 JSON 双引号：

```powershell
$body = @{
  session_id = "readme-demo"
  query = "比较 Milvus 与 Elasticsearch 在混合检索中的职责"
  mode = "hybrid"
  top_k = 5
  allow_web_fallback = $false
} | ConvertTo-Json -Compress

$curlBody = $body.Replace('"', '\"')

curl.exe -N `
  -X POST "http://127.0.0.1:8000/rag/chat/stream/events" `
  -H "Content-Type: application/json; charset=utf-8" `
  --data-raw "$curlBody"
```

启用认证后，在 `Invoke-RestMethod` 中传入 `-Headers @{ Authorization = "Bearer $token" }`，或为 `curl.exe` 增加 `-H ("Authorization: Bearer {0}" -f $token)`。也可以使用 `X-API-Key`。

## 关键功能开关

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `RAG_PIPELINE_PROVIDER` | `classic` | 选择 `classic` / `langgraph` / `rag_agent` |
| `AUTH_ENABLED` | `false` | 启用 JWT / API Key 强制认证 |
| `PROMPT_GUARD_ENABLED` | `true` | 启用输入、检索上下文和输出 Guard |
| `MEMORY_STORE_PROVIDER` | `in_memory` | 设为 `redis` 后使用 Redis 最近窗口 |
| `SUMMARY_MEMORY_ENABLED` | `false` | 启用 PostgreSQL ConversationSummary |
| `AGENT_DOCUMENT_TOOLS_ENABLED` | `false` | 启用知识文档 Agent 工具 |
| `AGENT_DOCUMENT_TOOLS_DRY_RUN_ONLY` | `true` | 限制文档工具只生成 dry-run 计划 |
| `AGENT_DOCUMENT_TOOLS_REQUIRE_CONFIRMATION` | `true` | 要求独立确认接口后才能执行 |
| `AGENT_TASK_MCP_ENABLED` | `false` | 启用受配置约束的 MCP stdio 工具 |
| `NL2SQL_ENABLED` | `false` | 启用 Dataset NL2SQL |
| `GITLAB_INTEGRATION_ENABLED` | `false` | 启用 GitLab 数据源、Webhook 与同步 |
| `GITLAB_AGENT_CHANGES_ENABLED` | `false` | 把确认后的文档变更转为 GitLab MR |
| `RAG_PARENT_EXPANSION_ENABLED` | `false` | 使用已重建的 v2 索引进行父块上下文扩展 |
| `LANGSMITH_TRACING` | `false` | 启用 LangSmith tracing |
| `DEBUG_TRACE_ENABLED` | `false` | 启用内部 debug trace API |

完整配置与默认值以 [`src/fast_app/core/config.py`](src/fast_app/core/config.py) 为准。生产或共享环境不要沿用匿名模式、占位密钥、默认数据库凭据或宽松的本地 CORS 配置。

## 数据与外部服务边界

| 组件 | 职责 |
| --- | --- |
| PostgreSQL | 用户、部门、RBAC、会话、Task audit、导入任务、GitLab 同步、NL2SQL Dataset/Grant 等业务事实 |
| Redis | 有 TTL 的最近对话窗口；不是授权或任务事实来源 |
| Milvus | 向量召回和版本/ACL filter |
| Elasticsearch | 关键词召回、metadata filter 和已发布知识索引 |
| GitLab | 企业文档源、版本身份、变更审查和 Merge Request 生命周期 |
| NL2SQL 业务库 | 独立只读连接；由 Dataset Registry、Grant、数据库角色和 RLS 共同约束 |
| LangSmith | RAG / Agent trace；自定义敏感字段默认不上传 |

GitLab 同步任务由独立常驻 Worker 处理，不在 FastAPI 请求内临时执行：

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m fast_app.integrations.gitlab.worker
```

## 测试与验证

所有脚本都从仓库根目录运行：

```powershell
$env:PYTHONPATH="src"
$env:LANGSMITH_TRACING="false"
$env:LANGCHAIN_TRACING_V2="false"
```

快速执行几组不依赖公网的确定性回归：

```powershell
.\.venv\Scripts\python.exe scripts\tests\agent_research\test_agent_task_router.py
.\.venv\Scripts\python.exe scripts\tests\agent_research\test_schema_field_descriptions.py
.\.venv\Scripts\python.exe scripts\tests\document_security\test_guarded_streaming.py
.\.venv\Scripts\python.exe scripts\tests\ingestion\test_markdown_parent_child.py
.\.venv\Scripts\python.exe scripts\tests\nl2sql\test_nl2sql_module.py
.\.venv\Scripts\python.exe scripts\tests\web_retrieval\test_enhanced_web_search.py
.\.venv\Scripts\python.exe scripts\tests\integrations\test_mcp_tool_adapter.py
```

测试是否需要 PostgreSQL、Redis、GitLab、ES/Milvus、真实模型或公网，以各分类说明为准：

- [测试总览](scripts/tests/readme.md)
- [RAG 与多轮会话](scripts/tests/rag_memory/readme.md)
- [Agent Router、TaskPlan 与 Research](scripts/tests/agent_research/readme.md)
- [文档 Agent、权限与安全](scripts/tests/document_security/readme.md)
- [Ingestion](scripts/tests/ingestion/readme.md)
- [NL2SQL](scripts/tests/nl2sql/readme.md)
- [Web 检索](scripts/tests/web_retrieval/readme.md)
- [GitLab、LangSmith、MCP 与代码桥接](scripts/tests/integrations/readme.md)

RAG 离线评测入口：

```powershell
.\.venv\Scripts\python.exe scripts\run_real_offline_rag_eval.py
```

## 深入文档

- [Agentic Research 多 Agent 代码学习指南](<scripts/docs/Agentic Research多Agent代码学习指南.md>)
- [Deep Agents 文档多 Agent 实现与验收指南](<scripts/docs/Deep Agents文档多Agent实现与验收指南.md>)
- [GitLab 企业文档资产管理后端实现教程](<scripts/docs/GitLab企业文档资产管理后端实现教程.md>)
- [NL2SQL 接口与部署说明](<scripts/docs/NL2SQL接口与部署说明.md>)
- [多 Agent 端到端测试复盘与工程规则](<scripts/docs/多Agent端到端测试复盘与工程规则.md>)
- [Ingestion 模块说明](src/fast_app/ingestion/README.md)
- [Evaluation 模块说明](src/fast_app/evaluation/README.md)

## 已知边界

- 仓库尚未提供可提交的 `.env.example`、Dockerfile 或 Docker Compose；本地完整环境不是一键启动。
- Agent Router 配置目前在应用启动阶段统一校验，`classic` provider 也需要提供三个 Router 环境变量。
- `create_agent()` 只用于对照和局部能力，未替换显式 LangGraph RAG Agent 主线。
- GitLab 同步与发布依赖独立 Worker；Merge Request 创建不代表发布、ES 和 Milvus 已完成最终一致性收敛。
- PPTX / XLSX、真实 NL2SQL、GitLab、Web 和真实模型验收都依赖外部环境；确定性脚本通过不等于完整线上链路已经验收。
- 旧 `/rag/chat/stream` 只保留兼容 token 流。所有新 sources、Guard、TaskPlan、Agent step 和错误事件都应走 `/rag/chat/stream/events`。

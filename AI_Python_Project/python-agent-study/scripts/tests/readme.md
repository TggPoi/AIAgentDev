# 测试脚本目录

本目录保存可重复执行的回归脚本。人工 Web 验收用于验证完整业务流程；这里的脚本用于验证 Schema、失败分支、权限、安全、稳定 ID、并发、外部适配器和存储契约。

## 目录

| 目录 | 内容 |
| --- | --- |
| `rag_memory` | RAG HTTP/SSE、Provider、多轮会话和摘要记忆 |
| `ingestion` | Markdown、父子 Chunk、PPTX/XLSX ingestion |
| `integrations` | GitLab、LangSmith、MCP、ChatGPT 只读桥接 |
| `nl2sql` | NL2SQL 安全、授权、API、路由和真实数据库 |
| `agent_research` | Router、TaskPlan、Research 编排和结构化输出 |
| `document_security` | 文档 Agent、Checkpoint、RBAC、ACL、Prompt Guard |
| `web_retrieval` | Web Search 适配器、过滤、正文、重定向和 Sitemap |

## 通用运行方式

在仓库根目录执行：

```powershell
$env:PYTHONPATH="src"
$env:LANGSMITH_TRACING="false"
$env:LANGCHAIN_TRACING_V2="false"
.\.venv\Scripts\python.exe scripts\tests\<分类目录>\<脚本名>.py
```

需要 PostgreSQL、Redis、GitLab、Milvus、ElasticSearch、真实 LLM 或公网的脚本，会在对应子目录的 `readme.md` 中注明前置条件。

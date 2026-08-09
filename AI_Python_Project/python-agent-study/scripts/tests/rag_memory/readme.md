# RAG 与会话记忆测试

## 脚本

| 脚本 | 作用 | 使用方式 |
| --- | --- | --- |
| `test_rag_chat_api.py` | 验证 `/rag/chat`、legacy token stream、结构化 SSE、sources、debug trace 和 RAG Agent 场景。 | 启动 FastAPI 后运行；可追加 `--rag-agent-suite`、`--structured-stream-only` 或 `--debug-trace-only`。 |
| `test_rag_provider_matrix.py` | 进程内验证 classic/langgraph 与不同 Retriever、LLM、Reranker Provider 的装配组合。 | 当前与依赖工厂新增的 `Request` 参数不兼容；保留用于后续修复，修复后可使用 `--mock-only` 或 `--real-only`。 |
| `test_multiturn_rag_agent.py` | 验证用户会话隔离、query rewrite、多轮持久化以及 `stream()`/`stream_events()` 契约。 | 需要对应的会话存储和真实模型配置；仅测改写可使用 `--rewrite-only`。 |
| `test_conversation_summary_memory.py` | 验证 PostgreSQL 会话摘要生成、版本、来源消息和摘要参与 query rewrite。 | 需要 PostgreSQL、会话数据和真实模型配置。 |

## 示例

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe scripts\tests\rag_memory\test_rag_chat_api.py --rag-agent-suite
.\.venv\Scripts\python.exe scripts\tests\rag_memory\test_rag_provider_matrix.py --list-scenarios
```

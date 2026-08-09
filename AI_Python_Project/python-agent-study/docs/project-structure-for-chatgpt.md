# python-agent-study 工程结构说明

这份文档用于把当前本地工程结构提交给网页版 ChatGPT，帮助它理解项目目录、核心模块、运行方式和当前 RAG 功能设计。文档不包含 `.env` 中的密钥值。

## 项目概览

项目名称：`python-agent-study`

项目路径：

```text
D:\AI_Agent_Project\AI_Python_Project\python-agent-study
```

这是一个 Python 学习和 RAG 应用实验项目，主要包含两部分：

1. `src/fast_app`：FastAPI 主应用，包含 API 路由、RAG pipeline、依赖注入、LLM/embedding/retriever 组件。
2. `src/app`：学习 demo、数据构造脚本、Milvus/Elasticsearch 写入脚本、LangChain/LangGraph/async 示例。

项目采用 `src` layout。运行模块时通常需要在项目根目录设置：

```powershell
$env:PYTHONPATH="src"
```

## 顶层目录

```text
python-agent-study/
├── .env
├── .gitignore
├── README.md
├── requirements.txt
├── data/
├── docs/
├── scripts/
├── src/
│   ├── app/
│   └── fast_app/
└── tests/
```

说明：

- `.env`：应用配置文件，包含 FastAPI、RAG、Milvus、Elasticsearch、Qwen/OpenAI-compatible API 等配置项。
- `requirements.txt`：Python 依赖声明。
- `data/`：示例数据文件。
- `docs/`：项目说明文档。
- `scripts/`：测试脚本，例如 RAG chat API 测试。
- `src/app/`：学习 demo 和数据导入脚本。
- `src/fast_app/`：FastAPI 应用主体。
- `tests/`：测试目录，目前未看到核心测试文件。

## 关键依赖

当前主要依赖包括：

```text
fastapi==0.136.1
uvicorn==0.47.0
pydantic==2.13.4
pydantic-settings==2.14.1
langchain==1.3.2
langchain-core==1.4.0
langchain-openai==1.2.2
langgraph==1.2.2
openai==2.38.0
pymilvus==3.0.0
elasticsearch==8.17.0
elastic-transport==8.17.1
aiohttp==3.14.0
httpx==0.28.1
requests==2.34.1
```

Elasticsearch Python client 当前是 `8.17.0`，用于匹配本地 Docker Elasticsearch `8.17.0`。

## FastAPI 主应用

入口文件：

```text
src/fast_app/main.py
```

作用：

- 创建 FastAPI app。
- 使用 lifespan 在启动/关闭时记录日志。
- 添加 CORS 中间件。
- 注册全局异常处理器。
- 挂载多个 API router。

挂载的 router：

```python
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(rag_router)
app.include_router(rag_chat_router)
app.include_router(stream_router)
app.include_router(error_demo_router)
```

启动命令：

```powershell
$env:PYTHONPATH="src"
python -m uvicorn fast_app.main:app --reload
```

## 配置系统

配置文件：

```text
src/fast_app/core/config.py
```

核心类：

```python
class Settings(BaseSettings)
```

配置读取方式：

- 使用 `pydantic-settings`。
- 默认读取项目根目录 `.env`。
- 使用 `@lru_cache` 缓存 `get_settings()` 结果。

主要配置项：

```text
APP_NAME
APP_ENV
DEBUG
RAG_DEFAULT_TOP_K
RAG_DEFAULT_MIN_SCORE
RAG_USE_MOCK
MILVUS_HOST
MILVUS_PORT
MILVUS_COLLECTION_NAME
MILVUS_VECTOR_FIELD
MILVUS_ID_FIELD
MILVUS_CONTENT_FIELD
ELASTICSEARCH_URL
ELASTICSEARCH_INDEX_NAME
ELASTICSEARCH_USERNAME
ELASTICSEARCH_PASSWORD
LOG_LEVEL
CORS_ALLOW_ORIGINS
OPENAI_API_KEY
OPENAI_BASE_URL
LLM_MODEL_NAME
LLM_PROVIDER
RAG_PIPELINE_PROVIDER
EMBEDDING_PROVIDER
EMBEDDING_MODEL_NAME
EMBEDDING_DIM
VECTOR_RETRIEVER_PROVIDER
KEYWORD_RETRIEVER_PROVIDER
```

当前 provider 设计：

- `LLM_PROVIDER`：支持 `mock`、`qwen`。
- `RAG_PIPELINE_PROVIDER`：支持 `classic`、`langgraph`。
- `EMBEDDING_PROVIDER`：当前支持 `qwen`。
- `VECTOR_RETRIEVER_PROVIDER`：支持 `mock`、`milvus`。
- `KEYWORD_RETRIEVER_PROVIDER`：支持 `mock`、`elasticsearch`。

## API 路由

### RAG Chat API

文件：

```text
src/fast_app/api/rag_chat_routes.py
```

路由前缀：

```text
/rag
```

接口：

```text
POST /rag/chat
POST /rag/chat/stream
```

`POST /rag/chat`：

- 接收 `RagChatRequest`。
- 通过 FastAPI `Depends(get_rag_pipeline)` 注入 pipeline。
- 调用 `pipeline.run(req)`。
- 返回完整 JSON 响应 `RagChatResponse`。

`POST /rag/chat/stream`：

- 接收 `RagChatRequest`。
- 注入 pipeline。
- 调用 `pipeline.stream(req)`。
- 使用 `StreamingResponse` 返回 SSE。
- 正常结束时发送：

```text
event: done
data: [DONE]
```

异常时发送 SSE error event：

```text
event: error
data: NO_SEARCH_RESULT: ...
```

或：

```text
event: error
data: EXTERNAL_SERVICE_ERROR: ...
```

## 请求和响应模型

文件：

```text
src/fast_app/schemas/rag_chat_schema.py
```

请求模型：

```python
class RagChatRequest(BaseModel):
    query: str
    mode: Literal["vector", "keyword", "hybrid"] = "hybrid"
    top_k: int = 5
    min_score: float = 0.0
```

约束：

- `query`：长度 1 到 500，且不能只包含空白字符。
- `mode`：只能是 `vector`、`keyword`、`hybrid`。
- `top_k`：1 到 20。
- `min_score`：0.0 到 1.0。
- `extra="forbid"`，禁止客户端传入未声明字段。

响应模型：

```python
class RagChatResponse(BaseModel):
    query: str
    answer: str
    sources: list[str]
```

## 内部业务模型

文件：

```text
src/fast_app/domain/rag_models.py
```

```python
@dataclass
class RetrievedDoc:
    id: str
    content: str
    score: float
    source: str

@dataclass
class RagContext:
    text: str
    docs: list[RetrievedDoc]
```

文件：

```text
src/fast_app/domain/knowledge_models.py
```

```python
@dataclass
class KnowledgeChunk:
    id: str
    content: str
    source: str
    title: str
```

## 依赖注入

文件：

```text
src/fast_app/dependencies/rag_dependencies.py
```

主要职责：

- 根据配置创建 LLM client。
- 根据配置创建 embedding client。
- 根据配置创建 vector retriever。
- 根据配置创建 keyword retriever。
- 根据配置创建 RAG pipeline。

核心函数：

```python
get_llm_client()
get_embedding_client()
get_vector_retriever()
get_keyword_retriever()
get_rag_pipeline()
```

选择逻辑：

```text
LLM_PROVIDER=mock        -> MockLLMClient
LLM_PROVIDER=qwen        -> QwenLangChainLLMClient

EMBEDDING_PROVIDER=qwen  -> QwenEmbeddingClient

VECTOR_RETRIEVER_PROVIDER=mock   -> MockVectorRetriever
VECTOR_RETRIEVER_PROVIDER=milvus -> MilvusVectorRetriever

KEYWORD_RETRIEVER_PROVIDER=mock          -> MockKeywordRetriever
KEYWORD_RETRIEVER_PROVIDER=elasticsearch -> ElasticsearchKeywordRetriever

RAG_PIPELINE_PROVIDER=classic   -> RagPipeline
RAG_PIPELINE_PROVIDER=langgraph -> LangGraphRagPipeline
```

注意：`get_vector_retriever()` 中没有把 `embedding_client` 声明为 `Depends(get_embedding_client)`，而是在 provider 为 `milvus` 时手动创建。这样可以避免 mock 模式下也提前初始化真实 embedding client。

## RAG Pipeline：classic 版本

文件：

```text
src/fast_app/services/rag/rag_pipeline_service.py
```

核心类：

```python
class RagPipeline
```

职责：

1. 根据请求的 `mode` 执行向量检索、关键词检索或混合检索。
2. 使用 `min_score` 过滤低分文档。
3. 在混合检索时并发调用两个 retriever。
4. 合并多路召回结果，按 `id` 去重，保留分数更高的版本。
5. 按分数排序并截断到 `top_k`。
6. 构造 `RagContext`。
7. 调用 LLM client 生成完整回答或流式 token。

主要方法：

```python
async def run(self, req: RagChatRequest) -> RagChatResponse
async def stream(self, req: RagChatRequest) -> AsyncGenerator[str, None]
async def retrieve(self, req: RagChatRequest) -> list[RetrievedDoc]
```

关键辅助函数：

```python
filter_docs_by_score(docs, min_score)
merge_docs_by_id(doc_lists, top_k)
build_context_node(docs)
```

混合检索使用：

```python
results = await asyncio.gather(
    self.vector_retriever.retrieve(req.query),
    self.keyword_retriever.retrieve(req.query),
    return_exceptions=True,
)
```

如果两个召回源都失败，抛出：

```python
ExternalServiceError("所有召回源都失败")
```

如果召回成功但过滤后没有结果，抛出：

```python
NoSearchResultError(...)
```

## RAG Pipeline：LangGraph 版本

文件：

```text
src/fast_app/services/rag/langgraph_rag_pipeline_service.py
src/fast_app/graph/rag/rag_graph_builder.py
src/fast_app/graph/rag/rag_graph_nodes.py
src/fast_app/graph/rag/rag_graph_state.py
```

核心类：

```python
class LangGraphRagPipeline
```

图结构：

```text
START -> retrieve -> build_context -> generate -> END
```

`build_rag_graph(...)` 使用：

```python
builder = StateGraph(GraphRagState)
builder.add_node("retrieve", create_retrieve_node(...))
builder.add_node("build_context", create_build_context_node())
builder.add_node("generate", create_generate_node(...))
return builder.compile()
```

`run()`：

- 构造 initial state。
- 调用 `self.graph.ainvoke(initial_state)`。
- 从 final state 中读取 `answer` 和 `docs`。
- 返回 `RagChatResponse`。

`stream()`：

- 当前没有使用完整 LangGraph stream。
- 手动执行 `retrieve_node` 和 `build_context_node`。
- 然后调用 `llm_client.stream(...)` 返回 token。

## LLM 组件

抽象基类：

```text
src/fast_app/components/llms/base.py
```

接口：

```python
async def generate(self, query: str, context: RagContext) -> str
async def stream(self, query: str, context: RagContext) -> AsyncGenerator[str, None]
```

Mock 实现：

```text
src/fast_app/components/llms/mock_llm_client.py
```

作用：

- 模拟 LLM 延迟。
- `generate()` 返回完整字符串。
- `stream()` 按字符流式返回。

Qwen/LangChain 实现：

```text
src/fast_app/components/llms/qwen_langchain_llm_client.py
```

作用：

- 使用 `langchain_openai.ChatOpenAI` 连接 OpenAI-compatible endpoint。
- 当前默认 base URL 是 DashScope compatible mode。
- 使用 `ChatPromptTemplate` 构造中文 RAG 提示词。
- `generate()` 使用 `chain.ainvoke(...)`。
- `stream()` 使用 `chain.astream(...)`。

系统提示词规则：

1. 优先根据给定检索上下文回答。
2. 如果上下文不足，说明无法从上下文确定。
3. 不编造上下文中不存在的信息。
4. 使用中文回答。

## Embedding 组件

抽象基类：

```text
src/fast_app/components/embeddings/base.py
```

接口：

```python
async def embed_query(self, text: str) -> list[float]
async def embed_documents(self, texts: list[str]) -> list[list[float]]
```

Qwen embedding 实现：

```text
src/fast_app/components/embeddings/qwen_embedding_client.py
```

使用：

```python
OpenAIEmbeddings(
    model=settings.embedding_model_name,
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    dimensions=settings.embedding_dim,
    check_embedding_ctx_length=False,
)
```

注意：

- `check_embedding_ctx_length=False` 是为了让 LangChain 直接发送原始字符串，而不是 token id 数组。
- 当前 embedding 维度配置为 `EMBEDDING_DIM`，默认 `1024`。

## Retriever 组件

抽象基类：

```text
src/fast_app/components/retrievers/base.py
```

接口：

```python
async def retrieve(self, query: str) -> list[RetrievedDoc]
```

### MockVectorRetriever

文件：

```text
src/fast_app/components/retrievers/mock_vector_retriever.py
```

返回模拟 Milvus 向量召回结果。

### MockKeywordRetriever

文件：

```text
src/fast_app/components/retrievers/mock_keyword_retriever.py
```

返回模拟 Elasticsearch 关键词召回结果。

### MilvusVectorRetriever

文件：

```text
src/fast_app/components/retrievers/milvus_vector_retriever.py
```

流程：

1. 使用 embedding client 将 query 转成向量。
2. 检查 query vector 维度是否等于 `settings.embedding_dim`。
3. 调用 `MilvusClient.search(...)`。
4. 使用 COSINE metric。
5. 返回 `RetrievedDoc` 列表，source 固定为 `"milvus"`。

搜索字段来自配置：

```text
MILVUS_COLLECTION_NAME
MILVUS_VECTOR_FIELD
MILVUS_ID_FIELD
MILVUS_CONTENT_FIELD
```

### ElasticsearchKeywordRetriever

文件：

```text
src/fast_app/components/retrievers/elasticsearch_keyword_retriever.py
```

流程：

1. 创建 `AsyncElasticsearch(hosts=[settings.elasticsearch_url])`。
2. 调用 `client.search(...)`。
3. 使用 `match` 查询 `content` 字段。
4. 读取 `response["hits"]["hits"]`。
5. 转换成 `RetrievedDoc` 列表，source 固定为 `"elasticsearch"`。

## 异常处理

业务异常定义：

```text
src/fast_app/services/exceptions.py
```

异常类型：

```python
AppServiceError
DocumentNotFoundError
NoSearchResultError
ExternalServiceError
LLMCallError
```

全局异常处理器：

```text
src/fast_app/core/exception_handlers.py
```

映射关系：

```text
NoSearchResultError   -> HTTP 404, code=NO_SEARCH_RESULT
ExternalServiceError  -> HTTP 503, code=EXTERNAL_SERVICE_ERROR
AppServiceError       -> HTTP 400, code=APP_SERVICE_ERROR
LLMCallError          -> HTTP 503, code=LLM_CALL_ERROR
Exception             -> HTTP 500, code=INTERNAL_SERVER_ERROR
```

注意：`LLMCallError` 继承自 `ExternalServiceError`。在 FastAPI 异常处理器匹配时，要注意父类/子类处理器注册顺序可能影响实际命中。

## 示例知识数据

文件：

```text
src/app/build_demo_chunks.py
```

函数：

```python
build_demo_chunks() -> list[KnowledgeChunk]
```

当前构造 7 条 demo chunk：

```text
rag_basic_001        RAG 基础
rag_vector_001       向量检索
rag_keyword_001      关键词检索
rag_hybrid_001       混合检索
milvus_basic_001     Milvus 基础
es_basic_001         ElasticSearch 基础
langgraph_basic_001  LangGraph 基础
```

这些 chunk 会被 Milvus 和 Elasticsearch ingest 脚本复用。

## Milvus 数据导入

文件：

```text
src/app/ingest_milvus_docs.py
```

建议运行方式：

```powershell
$env:PYTHONPATH="src"
python -m app.ingest_milvus_docs
```

作用：

1. 读取配置，连接 Milvus。
2. 调用 `build_demo_chunks()` 构造 demo 文档。
3. 如果 collection 不存在，则创建 collection。
4. 使用 Qwen/OpenAI-compatible embedding 模型生成文档向量。
5. 检查 embedding 维度。
6. 把 chunk 和 vector 组装成 rows。
7. 调用 `client.upsert(...)` 写入 Milvus。
8. `flush` 并 `load_collection`。
9. 执行一次 search smoke test。

Milvus schema：

```text
id       VARCHAR, primary key
embedding FLOAT_VECTOR, dim=EMBEDDING_DIM
content  VARCHAR
source   VARCHAR
title    VARCHAR
```

Milvus index：

```text
index_type = AUTOINDEX
metric_type = COSINE
```

## Elasticsearch 数据导入

文件：

```text
src/app/ingest_elasticsearch_docs.py
```

建议运行方式：

```powershell
$env:PYTHONPATH="src"
python -m app.ingest_elasticsearch_docs
```

作用：

1. 读取配置，创建 `AsyncElasticsearch` client。
2. 如果 index 不存在，则创建 index。
3. 调用 `build_demo_chunks()` 构造 demo 文档。
4. 使用 `async_bulk(...)` 批量写入文档。
5. `refresh=True`，方便后续立即搜索到写入内容。
6. 执行一次 search smoke test。

Elasticsearch mapping：

```text
id         keyword
content    text, analyzer=ik_max_word, search_analyzer=ik_smart
title      text, analyzer=ik_max_word, search_analyzer=ik_smart, title.keyword=keyword
source     keyword
created_at date
```

注意：

- 本地 Elasticsearch 需要安装或内置 IK analyzer，否则 `ik_max_word` / `ik_smart` mapping 创建会失败。
- 当前异步 client 需要安装 `aiohttp`，requirements 中已经包含 `aiohttp==3.14.0`。

## API 测试脚本

文件：

```text
scripts/tests/rag_memory/test_rag_chat_api.py
```

运行前先启动 FastAPI：

```powershell
$env:PYTHONPATH="src"
python -m uvicorn fast_app.main:app --reload
```

另开终端执行：

```powershell
python scripts/tests/rag_memory/test_rag_chat_api.py
```

默认测试：

1. `POST /rag/chat` 正常响应。
2. `POST /rag/chat/stream` 正常 SSE 流式响应。
3. `POST /rag/chat` 异常响应，使用 `min_score=1.0` 触发 `NoSearchResultError`，期望 HTTP 404。
4. `POST /rag/chat/stream` 异常响应，期望 SSE `event: error`。

常用参数：

```powershell
python scripts/tests/rag_memory/test_rag_chat_api.py --query "RAG 是什么？" --mode hybrid --top-k 3 --min-score 0.0
python scripts/tests/rag_memory/test_rag_chat_api.py --stream-only
python scripts/tests/rag_memory/test_rag_chat_api.py --skip-errors
```

请求 payload 结构：

```json
{
  "query": "什么是混合检索？",
  "mode": "hybrid",
  "top_k": 5,
  "min_score": 0.0
}
```

## `src/app` 中的学习 demo

`src/app` 目录包含大量学习脚本，主要覆盖：

```text
async / await 示例
LangChain 示例
LangGraph 示例
Pydantic 示例
文件 IO 示例
类型标注示例
RAG 分阶段 demo
Milvus / Elasticsearch ingest 和 retriever demo
Qwen / embedding 最小调用 demo
```

重要脚本：

```text
src/app/embedding_minimal_demo.py
src/app/langchain_qwen_minimal_demo.py
src/app/ingest_milvus_docs.py
src/app/ingest_elasticsearch_docs.py
src/app/milvus_vector_retriever_demo.py
src/app/elasticsearch_keyword_retriever_demo.py
src/app/build_demo_chunks.py
src/app/langgraph_rag_demo.py
src/app/langgraph_rag_nodes_demo.py
```

## 推荐运行顺序

### 只用 mock 模式测试 RAG API

`.env` 中使用：

```text
LLM_PROVIDER=mock
VECTOR_RETRIEVER_PROVIDER=mock
KEYWORD_RETRIEVER_PROVIDER=mock
RAG_PIPELINE_PROVIDER=classic
```

启动服务：

```powershell
$env:PYTHONPATH="src"
python -m uvicorn fast_app.main:app --reload
```

运行 API 测试：

```powershell
python scripts/tests/rag_memory/test_rag_chat_api.py
```

### 使用真实 Milvus + Elasticsearch + Qwen

需要准备：

1. Milvus 服务可访问。
2. Elasticsearch 8.17.0 服务可访问。
3. Elasticsearch 支持当前 mapping 中的 IK analyzer。
4. `.env` 配置 OPENAI-compatible API key/base URL/model。

先写入 demo 数据：

```powershell
$env:PYTHONPATH="src"
python -m app.ingest_milvus_docs
python -m app.ingest_elasticsearch_docs
```

然后 `.env` 中使用：

```text
LLM_PROVIDER=qwen
EMBEDDING_PROVIDER=qwen
VECTOR_RETRIEVER_PROVIDER=milvus
KEYWORD_RETRIEVER_PROVIDER=elasticsearch
RAG_PIPELINE_PROVIDER=classic
```

启动服务并测试：

```powershell
$env:PYTHONPATH="src"
python -m uvicorn fast_app.main:app --reload
python scripts/tests/rag_memory/test_rag_chat_api.py
```

## 当前工程的关键设计点

1. FastAPI API 层只处理 HTTP 请求、依赖注入、SSE 包装和异常事件包装。
2. RAG pipeline 层负责检索、过滤、合并、上下文构造和 LLM 调用。
3. LLM、embedding、retriever 都通过抽象基类和 provider 配置解耦。
4. mock 组件用于离线学习和快速测试。
5. Milvus 和 Elasticsearch 组件用于真实混合检索。
6. classic pipeline 和 LangGraph pipeline 并存，通过配置选择。
7. `src/app` 中保留大量学习脚本，`src/fast_app` 是当前应用主体。
8. 项目使用 `.env` 管理配置，不应在提交给外部模型时泄露 `OPENAI_API_KEY`。

## 给网页版 ChatGPT 的建议提问方式

可以把本文件内容粘贴给 ChatGPT，然后追加你的具体问题，例如：

```text
以上是我的 Python/FastAPI RAG 项目结构。请基于这个项目结构，帮我分析 XXX 文件中的 XXX 函数，要求结合项目调用链解释，不要泛泛讲概念。
```

或者：

```text
以上是我的项目结构。请帮我设计下一步如何把当前 RAG pipeline 从 mock 模式切换到真实 Milvus + Elasticsearch + Qwen 模式，并指出需要修改哪些配置和文件。
```

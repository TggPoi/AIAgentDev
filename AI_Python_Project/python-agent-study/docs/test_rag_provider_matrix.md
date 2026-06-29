# test_rag_provider_matrix.py 使用说明

这个文档解释 `scripts/test_rag_provider_matrix.py` 的用途、运行方式、覆盖的测试场景，以及每个测试用例内部做了什么。

## 脚本用途

`test_rag_provider_matrix.py` 用来测试当前 RAG 工程中 5 个 provider 配置项的组合是否可以正确创建组件并执行 RAG pipeline。

被测试的 5 个配置项是：

```text
LLM_PROVIDER
EMBEDDING_PROVIDER
VECTOR_RETRIEVER_PROVIDER
KEYWORD_RETRIEVER_PROVIDER
RAG_PIPELINE_PROVIDER
```

当前工程支持的取值是：

```text
LLM_PROVIDER: mock / qwen
EMBEDDING_PROVIDER: qwen
VECTOR_RETRIEVER_PROVIDER: mock / milvus
KEYWORD_RETRIEVER_PROVIDER: mock / elasticsearch
RAG_PIPELINE_PROVIDER: classic / langgraph
```

因此 provider 组合数量是：

```text
2 * 1 * 2 * 2 * 2 = 16
```

## 和 test_rag_chat_api.py 的区别

`test_rag_chat_api.py` 是 HTTP API 测试脚本，它要求你先启动 FastAPI 服务，然后通过 HTTP 请求测试：

```text
POST /rag/chat
POST /rag/chat/stream
```

`test_rag_provider_matrix.py` 不走 HTTP，也不需要启动 FastAPI 服务。它会直接调用项目里的依赖注入函数，创建 retriever、LLM client、pipeline，然后直接执行：

```python
pipeline.run(req)
pipeline.stream(req)
```

这样做的原因是：provider 配置会影响依赖注入阶段创建哪些组件。如果用 HTTP 测试，每换一组 provider 配置就需要重启一次 FastAPI 服务；矩阵测试脚本可以在同一个进程里逐组覆盖环境变量并测试。

## 基本运行方式

在项目根目录运行：

```powershell
python scripts/test_rag_provider_matrix.py --list-scenarios
```

只列出所有 provider 组合，不执行测试。

运行 mock-only 场景：

```powershell
python scripts/test_rag_provider_matrix.py --mock-only
```

运行所有 provider 组合，默认只测试请求 mode=`hybrid`：

```powershell
python scripts/test_rag_provider_matrix.py
```

运行所有 provider 组合，并测试三种请求 mode：

```powershell
python scripts/test_rag_provider_matrix.py --all-modes
```

同时测试非流式和流式 pipeline：

```powershell
python scripts/test_rag_provider_matrix.py --all-modes --include-stream
```

## 场景分类

脚本会把 provider 组合打印成两类：

```text
[mock-safe]
[external]
```

`mock-safe` 表示不依赖真实 Qwen、Milvus、Elasticsearch。当前只有这两组：

```text
llm=mock, embedding=qwen, vector=mock, keyword=mock, pipeline=classic
llm=mock, embedding=qwen, vector=mock, keyword=mock, pipeline=langgraph
```

虽然 `EMBEDDING_PROVIDER=qwen`，但当 `VECTOR_RETRIEVER_PROVIDER=mock` 时，不会创建真实 embedding client，所以这两组可以离线运行。

`external` 表示至少包含以下真实外部服务之一：

```text
LLM_PROVIDER=qwen
VECTOR_RETRIEVER_PROVIDER=milvus
KEYWORD_RETRIEVER_PROVIDER=elasticsearch
```

这些场景可能需要：

- `.env` 中存在可用的 `OPENAI_API_KEY`。
- Qwen/OpenAI-compatible API 可访问。
- Milvus 服务已启动，并且 demo collection 已写入。
- Elasticsearch 服务已启动，并且 demo index 已写入。
- Elasticsearch 支持当前 mapping 使用的 IK analyzer。

## 16 个 provider 组合

脚本会覆盖下面 16 个 provider 组合：

```text
01. llm=mock, embedding=qwen, vector=mock, keyword=mock, pipeline=classic
02. llm=mock, embedding=qwen, vector=mock, keyword=mock, pipeline=langgraph
03. llm=mock, embedding=qwen, vector=mock, keyword=elasticsearch, pipeline=classic
04. llm=mock, embedding=qwen, vector=mock, keyword=elasticsearch, pipeline=langgraph
05. llm=mock, embedding=qwen, vector=milvus, keyword=mock, pipeline=classic
06. llm=mock, embedding=qwen, vector=milvus, keyword=mock, pipeline=langgraph
07. llm=mock, embedding=qwen, vector=milvus, keyword=elasticsearch, pipeline=classic
08. llm=mock, embedding=qwen, vector=milvus, keyword=elasticsearch, pipeline=langgraph
09. llm=qwen, embedding=qwen, vector=mock, keyword=mock, pipeline=classic
10. llm=qwen, embedding=qwen, vector=mock, keyword=mock, pipeline=langgraph
11. llm=qwen, embedding=qwen, vector=mock, keyword=elasticsearch, pipeline=classic
12. llm=qwen, embedding=qwen, vector=mock, keyword=elasticsearch, pipeline=langgraph
13. llm=qwen, embedding=qwen, vector=milvus, keyword=mock, pipeline=classic
14. llm=qwen, embedding=qwen, vector=milvus, keyword=mock, pipeline=langgraph
15. llm=qwen, embedding=qwen, vector=milvus, keyword=elasticsearch, pipeline=classic
16. llm=qwen, embedding=qwen, vector=milvus, keyword=elasticsearch, pipeline=langgraph
```

## 请求 mode 场景

provider 组合之外，RAG 请求本身还有 3 种 `mode`：

```text
vector
keyword
hybrid
```

默认只测试：

```text
hybrid
```

如果使用：

```powershell
python scripts/test_rag_provider_matrix.py --all-modes
```

那么每个 provider 组合都会分别测试：

```text
mode=vector
mode=keyword
mode=hybrid
```

总用例数量会变成：

```text
16 provider 组合 * 3 request modes = 48 个 run 用例
```

如果再加：

```powershell
--include-stream
```

每个用例会同时执行 `run` 和 `stream`，总操作数量会变成：

```text
48 * 2 = 96 个操作
```

## 每个测试用例做了什么

对每一个 provider 组合和请求 mode，脚本会执行以下步骤：

1. 保存当前进程中相关环境变量的原始值。
2. 临时覆盖 5 个 provider 环境变量。
3. 临时设置 `DEBUG=true`，避免外部 shell 中的非布尔值干扰 Pydantic 配置解析。
4. 调用 `get_settings.cache_clear()`，强制下一次读取配置时使用新的环境变量。
5. 调用 `get_settings()` 创建新的 `Settings` 对象。
6. 调用 `get_vector_retriever(settings=settings)` 创建向量检索器。
7. 调用 `get_keyword_retriever(settings=settings)` 创建关键词检索器。
8. 调用 `get_llm_client(settings=settings)` 创建 LLM client。
9. 调用 `get_rag_pipeline(...)` 创建 `RagPipeline` 或 `LangGraphRagPipeline`。
10. 构造 `RagChatRequest`。
11. 调用 `pipeline.run(req)`。
12. 如果开启了 `--include-stream`，再调用 `pipeline.stream(req)` 并消费 token。
13. 记录 PASS 或 FAIL。
14. 如果组件有 `close()` 方法，则调用关闭方法。
15. 恢复原始环境变量。
16. 再次调用 `get_settings.cache_clear()`，避免当前用例配置污染下一个用例。

## 测试通过的判断

`pipeline.run(req)` 通过的条件：

- pipeline 成功创建。
- retriever 和 LLM client 成功创建。
- `pipeline.run(req)` 在超时时间内完成。
- 返回的 response 中可以读取 `answer` 和 `sources`。

输出示例：

```text
[PASS] mode=hybrid, operation=run, llm=mock, embedding=qwen, vector=mock, keyword=mock, pipeline=classic
       answer_length=283, sources=['doc_milvus_001', 'doc_es_001', 'doc_shared_001']
```

`pipeline.stream(req)` 通过的条件：

- `pipeline.stream(req)` 可以开始返回 token。
- 脚本成功消费到指定数量的字符，或完整消费结束。
- 没有在流式过程中抛异常。

输出示例：

```text
[PASS] mode=hybrid, operation=stream, llm=mock, embedding=qwen, vector=mock, keyword=mock, pipeline=classic
       stream_chars=200
```

## 常用参数

### --list-scenarios

只打印 provider 组合，不执行测试：

```powershell
python scripts/test_rag_provider_matrix.py --list-scenarios
```

### --mock-only

只运行 mock-safe 组合：

```powershell
python scripts/test_rag_provider_matrix.py --mock-only
```

适合快速验证 pipeline 代码结构，不依赖外部服务。

### --real-only

只运行至少包含真实外部服务的组合：

```powershell
python scripts/test_rag_provider_matrix.py --real-only
```

适合在 Milvus、Elasticsearch、Qwen 都准备好之后测试真实链路。

### --modes

指定要测试的请求 mode：

```powershell
python scripts/test_rag_provider_matrix.py --modes vector keyword
```

### --all-modes

测试全部请求 mode：

```powershell
python scripts/test_rag_provider_matrix.py --all-modes
```

### --include-stream

同时测试 `pipeline.stream(req)`：

```powershell
python scripts/test_rag_provider_matrix.py --include-stream
```

### --stream-char-limit

限制流式测试最多消费多少字符：

```powershell
python scripts/test_rag_provider_matrix.py --include-stream --stream-char-limit 100
```

如果设置为 `0`，表示完整消费流：

```powershell
python scripts/test_rag_provider_matrix.py --include-stream --stream-char-limit 0
```

### --timeout

设置单个 `run` 或 `stream` 操作的超时时间：

```powershell
python scripts/test_rag_provider_matrix.py --timeout 120
```

### --stop-on-failure

遇到第一个失败用例后停止：

```powershell
python scripts/test_rag_provider_matrix.py --stop-on-failure
```

### --query / --top-k / --min-score

自定义 RAG 请求参数：

```powershell
python scripts/test_rag_provider_matrix.py --query "RAG 是什么？" --top-k 5 --min-score 0.0
```

## 推荐测试顺序

第一步，只看组合：

```powershell
python scripts/test_rag_provider_matrix.py --list-scenarios
```

第二步，跑离线 mock 组合：

```powershell
python scripts/test_rag_provider_matrix.py --mock-only
```

第三步，跑 mock 组合的三种请求 mode：

```powershell
python scripts/test_rag_provider_matrix.py --mock-only --all-modes
```

第四步，如果真实服务已经准备好，再跑真实组合：

```powershell
python scripts/test_rag_provider_matrix.py --real-only --all-modes
```

第五步，最后再加流式测试：

```powershell
python scripts/test_rag_provider_matrix.py --real-only --all-modes --include-stream
```

## 真实服务测试前置条件

如果要运行包含 `qwen`、`milvus`、`elasticsearch` 的组合，需要先确认：

```text
OPENAI_API_KEY 已配置
OPENAI_BASE_URL 可访问
LLM_MODEL_NAME 可用
EMBEDDING_MODEL_NAME 可用
Milvus 服务可访问
Milvus collection 已写入 demo chunks
Elasticsearch 服务可访问
Elasticsearch index 已写入 demo chunks
Elasticsearch mapping 中使用的 IK analyzer 可用
```

可先运行数据写入脚本：

```powershell
$env:PYTHONPATH="src"
python -m app.ingest_milvus_docs
python -m app.ingest_elasticsearch_docs
```

## 常见失败含义

如果 `LLM_PROVIDER=qwen` 的组合失败，常见原因是：

```text
OPENAI_API_KEY 为空或无效
OPENAI_BASE_URL 无法访问
LLM_MODEL_NAME 配置错误
外部模型服务超时
```

如果 `VECTOR_RETRIEVER_PROVIDER=milvus` 的组合失败，常见原因是：

```text
Milvus 未启动
MILVUS_HOST / MILVUS_PORT 配置错误
collection 不存在
collection 未 load
embedding 维度和 collection 向量字段维度不匹配
```

如果 `KEYWORD_RETRIEVER_PROVIDER=elasticsearch` 的组合失败，常见原因是：

```text
Elasticsearch 未启动
ELASTICSEARCH_URL 配置错误
index 不存在
没有写入 demo 文档
IK analyzer 缺失导致 index 创建失败
```

如果一开始就出现 `Settings` 校验错误，通常是某个环境变量类型不符合 `src/fast_app/core/config.py` 中的 Pydantic 类型定义。脚本已经临时覆盖 `DEBUG=true`，但其他配置项仍然可能因为外部 shell 环境变量覆盖 `.env` 而失败。

## 注意事项

- 这个脚本不会修改 `.env` 文件。
- 这个脚本不需要启动 FastAPI 服务。
- 这个脚本会临时覆盖当前进程环境变量，并在每个用例结束后恢复。
- 这个脚本会调用 `get_settings.cache_clear()`，确保每组 provider 配置都能重新读取。
- 包含真实外部服务的组合会产生真实 API 调用或连接本地 Milvus/Elasticsearch。
- `--include-stream` 默认只消费前 200 个字符，避免流式输出测试耗时过长。

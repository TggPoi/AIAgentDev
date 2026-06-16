测试脚本使用方式：

运行前先启动 FastAPI 服务：

```powershell
$env:PYTHONPATH="src"
python -m uvicorn fast_app.main:app --reload
```

另开一个终端运行测试脚本：

```powershell
python scripts/test_rag_chat_api.py
```

它会依次测试：

- `POST /rag/chat`：打印完整 JSON 响应
- `POST /rag/chat/stream`：实时打印 SSE 流式输出效果

也可以只看流式输出：

```powershell
python scripts/test_rag_chat_api.py --stream-only
```

可自定义参数：

```powershell
python scripts/test_rag_chat_api.py --query "RAG 是什么？" --mode hybrid --top-k 3 --min-score 0.8
```

已更新 [test_rag_chat_api.py](d:/AI_Agent_Project/AI_Python_Project/python-agent-study/scripts/test_rag_chat_api.py)，现在默认会测试 4 种情况：

- `/rag/chat` 正常响应：期望 `200`
- `/rag/chat/stream` 正常流式响应：期望 `200` + `[DONE]`
- `/rag/chat` 异常响应：使用 `min_score=1.0` 触发 `NoSearchResultError`，期望全局异常处理器返回 `404`
- `/rag/chat/stream` 异常响应：使用 `min_score=1.0` 触发 SSE `event: error`

运行方式不变：

```powershell
python scripts/test_rag_chat_api.py
```

如果只想测试正常情况，不跑异常用例：

```powershell
python scripts/test_rag_chat_api.py --skip-errors
```

如果只测试流式接口，包括流式异常：

```powershell
python scripts/test_rag_chat_api.py --stream-only
```

已启动程序并运行测试脚本，正常情况和异常情况都通过。


2026年6月12日：========================
已更新 [scripts/test_rag_chat_api.py](d:/AI_Agent_Project/AI_Python_Project/python-agent-study/scripts/test_rag_chat_api.py)。

现在脚本支持新增参数：

```powershell
.\.venv\Scripts\python.exe scripts\test_rag_chat_api.py `
  --mode hybrid `
  --top-k 3 `
  --candidate-k 10 `
  --source-path "src/app/demo_docs/rag_intro.md" `
  --section-path "RAG 基础"
```

也可以重复传多个章节过滤值：

```powershell
.\.venv\Scripts\python.exe scripts\test_rag_chat_api.py `
  --mode hybrid `
  --top-k 3 `
  --candidate-k 10 `
  --section-path "RAG 基础" `
  --section-path "混合检索"
```

这次改动包括：

- `--candidate-k`：写入请求体的 `candidate_k`
- `--source-path`：写入 `filters.source_path`
- `--section-path`：写入 `filters.section_path`，支持重复传参
- 普通 `/rag/chat` 和流式 `/rag/chat/stream` 会共用同一份 payload
- 如果传了 filters，普通接口返回后会检查 `sources[*].metadata` 是否符合过滤条件

已验证：

```powershell
.\.venv\Scripts\python.exe -m py_compile scripts\test_rag_chat_api.py
```

语法检查通过。


执行结果包含 4 个用例：

```text
POST /rag/chat
status: 200
```

普通接口正常返回了回答和 sources。

```text
POST /rag/chat/stream
status: 200
```

流式接口正常输出，并最终返回：

```text
[done] [DONE]
```

异常测试：

```text
POST /rag/chat error
status: 404
```

全局异常处理器返回：

```json
{
  "code": "NO_SEARCH_RESULT",
  "message": "没有找到满足 min_score=1.0 的混合检索结果"
}
```

流式异常测试：

```text
POST /rag/chat/stream error
status: 200

event: error
data: NO_SEARCH_RESULT: 没有找到满足 min_score=1.0 的混合检索结果
```


2026年6月16日：========================
已更新 [scripts/test_rag_chat_api.py](d:/AI_Agent_Project/AI_Python_Project/python-agent-study/scripts/test_rag_chat_api.py:12)。

主要改动：

- 新增阶段 9 LangSmith 批量测试场景 `--phase9-langsmith-suite`
- 每次请求都会自动带 `X-Request-ID`，方便在 LangSmith metadata 和本地日志中对齐
- 新增 `--request-id`，可以给单次测试指定固定 request_id
- 新增 `--request-id-prefix`，批量场景会生成类似：
  `langsmith-phase9-xxxxxx-01-phase9-model-refactor`
- 支持批量场景额外测试结构化流式接口：`--suite-structured-stream`
- 默认 query 改成更贴合当前数据的阶段 9 问题

已验证：

```text
py_compile 通过
--help 输出正常
```

你可以这样运行阶段 9 LangSmith 批量测试：

```powershell
.\.venv\Scripts\python.exe scripts\test_rag_chat_api.py --phase9-langsmith-suite
```

如果还想让 `/rag/chat/stream/events` 也产生 LangSmith trace：

```powershell
.\.venv\Scripts\python.exe scripts\test_rag_chat_api.py --phase9-langsmith-suite --suite-structured-stream
```

前提是服务端启动时已经开启：

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=你的 key
```

并且要重启 `uvicorn`，让服务端重新读取 `.env`。
# AGENTS.md

## Project rules

This project is a Python / FastAPI / LangGraph / RAG Agent backend learning project.

Before doing project work, read these files in order:

1. `教学讲解规范.md`
2. `当前学习进度.md`
3. `学习路线优先级.md`
4. `总学习路线_归档参考.md`

`总学习路线_归档参考.md` is archived reference only.

Do not replace the explicit LangGraph RAG pipeline with `create_agent()` unless the user explicitly asks and a design review has been completed.

`pipeline.stream_events()` is the main structured streaming interface. It may emit guarded answer events such as `answer_delta`, `guard_sanitized`, and `guard_blocked`.

`pipeline.stream()` and `POST /rag/chat/stream` are compatibility-only legacy token streams. Do not add new enterprise frontend, Prompt Guard, sources, Agent step, or tool-call features to this legacy stream path.

For the enterprise-system conversion, keep only two RAG chat endpoints as the mainline:

1. `POST /rag/chat`
   - Non-streaming RAG chat.
   - Returns the complete answer, sources, request_id, and trace_id.
   - Use this for evaluation, debugging, admin workflows, and non-streaming React calls.

2. `POST /rag/chat/stream/events`
   - Structured SSE RAG chat.
   - Uses `pipeline.stream_events()`.
   - Use this as the main React streaming interface for sources, guarded answer deltas, guard events, done, and error events.

`POST /rag/chat/stream` is a deprecated compatibility-only token stream. Prefer `POST /rag/chat/stream/events` for all new work.

Do not modify `src/app` or `app` temporary learning code unless explicitly requested.

Use Windows PowerShell commands and `curl.exe` examples.

When generating PowerShell examples that call `curl.exe` with JSON request bodies, do not pass the raw `ConvertTo-Json` result directly to `--data-raw`. Windows PowerShell can strip JSON double quotes when invoking native executables. Use one of these patterns:

```powershell
$body = @{ query = "测试"; mode = "hybrid"; top_k = 1 } | ConvertTo-Json -Compress
$curlBody = $body.Replace('"', '\"')
curl.exe -N `
  -X POST "http://127.0.0.1:8000/rag/chat/stream/events" `
  -H "Content-Type: application/json; charset=utf-8" `
  -H ("Authorization: Bearer {0}" -f $token) `
  --data-raw "$curlBody"
```

For ordinary non-stream JSON APIs, prefer `Invoke-RestMethod` in PowerShell. For SSE / streaming APIs, use `curl.exe -N` and either escaped `$curlBody` as above or `--data-binary "@path\to\body.json"`.

The FastAPI module is `fast_app`.

Before file-level modifications, read the real code and dependency files. If docs and code disagree, code is the source of truth.

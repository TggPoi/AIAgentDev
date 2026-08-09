# AGENTS.md

## Project rules

This project is a Python / FastAPI / LangGraph / RAG Agent backend learning project.

The final system must support a React-based web frontend for visual operations. Backend design should therefore expose stable, structured, frontend-friendly APIs and SSE events for RAG chat, document management, tool plan review, human confirmation, permission status, evaluation, and observability. Do not design new control actions only as natural-language chat prompts when they should be buttons, forms, dialogs, or task-status views in React.

Before doing project work, read these files in order:

1. `learning-docs\教学讲解规范.md`
4. `learning-docs\总学习路线_归档参考.md`

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

For high-risk Agent operations such as creating, updating, or deleting knowledge-base documents, prefer dedicated backend control APIs that React can call directly. For example, confirmation should use an endpoint such as `POST /agent/tool-plans/{plan_id}/confirm` rather than relying only on `/rag/chat` query text.

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

## Pydantic and JSON Schema rules

1. Every public field in a Pydantic model that generates JSON Schema for LLM structured output, `response_format`, Tool `args_schema`, or FastAPI/OpenAPI requests and responses must declare `Field(description="...")`.
2. A field description must state the field's business meaning and, when relevant, its source, allowed status or enum semantics, identity inheritance, null/default meaning, and trust boundary. Keep it concise, but do not rely on the field name alone to convey these rules.
3. Class docstrings, Python comments, prompts, and validators do not replace field-level descriptions. Descriptions guide the model or API consumer; Pydantic validators and deterministic service checks must still enforce the rules.
4. When adding or changing a Schema-bound Pydantic model, extend and run `scripts/tests/agent_research/test_schema_field_descriptions.py` so missing field descriptions fail regression checks.

## Conversation context and Agent state rules

Use conversation history as scoped input, not as global implicit Agent state:

1. Load the Redis recent window and PostgreSQL summary once at the RAG pipeline boundary, then pass the frozen request snapshot through `RagAgentState`. Do not make downstream nodes independently reread conversation storage.
2. The current rewritten query always takes precedence over older conversation content. Keep history bounded and prefer recent messages over the summary when they conflict.
3. Only Planner, final answer generation, and the document Agent's frozen initial task context may consume conversation context. Do not automatically inject it into every LLM call.
4. Keep document Tool Loops task-local: initialize them from the frozen TaskPlan query/objective, then append only that task's `AIMessage` and `ToolMessage` values.
5. Conversation history is never an authorization or execution fact. Prompt Guard, permission checks, candidate `doc_id` scope, path validation, exact replacements, confirm, rollback, ES, and Milvus synchronization must continue to use current server-side facts.
6. Prompt Guard must classify the explicit boundary text it is given, such as the current raw query, rewritten query, retrieved document, or output. Do not silently prepend the full conversation history to classifier inputs.
7. Resume, cancel, retry, and confirm unfinished Agent work by `task_plan_id` and a dedicated backend control API/checkpoint. Do not infer these control actions only from natural-language conversation memory.
8. Conversation text included in custom LangSmith data must use the shared sensitive-field policy in `fast_app.core.langsmith`. SDK-instrumented model prompts remain subject to the platform-level tracing warning below.

## LangSmith observability rules

Use the pattern "centralized tracing policy, distributed business instrumentation":

1. Keep LangSmith enablement, environment synchronization, common metadata/tags, naming conventions, sensitive-data policy, and reusable trace builders in `src/fast_app/core/langsmith.py`.
2. New pipelines and business modules must reuse the high-level helpers in `fast_app.core.langsmith`; do not manually repeat `request_id`, `trace_id`, `app_name`, `app_env`, environment tags, or global LangSmith tags.
3. Keep the actual trace context and `add_outputs()` calls next to the business operation or LangGraph node whose boundary and safe output they describe. Do not hide all instrumentation behind middleware, decorators, a `LangSmithManager`, or speculative abstraction.
4. Domain-specific trace fields belong to the domain module. If the same trace assembly appears twice, extract the smallest local helper or extend an existing core helper instead of creating another tracing layer.
5. Custom LangSmith inputs, metadata, and outputs must pass through the shared sensitive-field policy before including query text, retrieval filters, or user IDs. `LANGSMITH_INCLUDE_SENSITIVE_DATA=true` may enable those custom fields only in a controlled environment. SDK-instrumented LangChain calls can still upload prompts and model outputs when tracing is enabled, so do not enable LangSmith against sensitive production traffic without an explicit platform-level redaction policy.
6. Any change to shared LangSmith builders or naming conventions must update and run `scripts/tests/integrations/test_langsmith_tracing.py`.

## Agent intent routing rules

1. New business intents must extend the structured `AgentTaskRouter` schema and its tests. Do not grow `_is_complex_question()`-style keyword routing into the production mainline.
2. The Router only decides intent. It must not generate trusted document steps, paths, doc IDs, ACL values, or Tool arguments.
3. Knowledge-document TaskPlan steps may only be created from document dry-run ToolCalls that passed server-side validation.
4. A Router decision never replaces authorization, candidate-scope checks, path validation, document preview, or human confirmation.

## Deep document multi-Agent rules

Use `scripts/docs/多Agent端到端测试复盘与工程规则.md` as the durable incident
runbook for Researcher / Writer / Reviewer / Coordinator work.

1. Prompt instructions never replace deterministic workflow state. Researcher failure, missing evidence, repeated dispatch, revision limits, tool limits, and terminal-state convergence must be enforced by server-side code that survives checkpoint resume.
2. If Researcher fails or returns no valid evidence and fixed-path summary, the affected deliverable must fail immediately. Do not dispatch Writer or Reviewer, and do not allow Writer to continue from general knowledge.
3. Give each role only its real Tool Schema before the model call. Researcher, Writer, and Reviewer must not see `write_todos`; Coordinator must not use document file tools to take over failed Writer work.
4. Keep separate and observable limits for shared model calls, per-role model calls, tool calls, context size, revision rounds, per-request timeout, and whole-workflow wall-clock time. A maximum budget is a fuse, not an acceptable normal-path target.
5. Use one deterministic draft path per deliverable. Prefer one bounded full-file read and batched independent edits over repeated discovery, pagination, and serial edit loops.
6. After Reviewer approval, assemble `DocumentWorkflowResult` deterministically from the approved draft and review result. Do not ask Coordinator to regenerate the full document.
7. Operation, doc ID, target path, source/project identity, base SHA, ACL, and publication version are trusted server-side facts. Writer and Reviewer output must never override them.
8. Test LangGraph middleware and runtime injection through a compiled graph with `invoke()` or `ainvoke()`; direct function calls alone do not validate the framework contract.
9. Use an old TaskPlan only for resume/recovery testing. After a workflow fix, successful acceptance must use a new TaskPlan with no inherited failed or repeated-dispatch history.
10. A document target path must remain identical across TaskPlan preview, dry-run, GitLab Commit, Compare diff, ACL matching, Manifest, and notification events. Do not strip department prefixes based on Project assumptions.
11. MR creation is not lifecycle completion. Reconcile local change-request state with GitLab `opened/merged/closed`, and verify the post-merge Webhook, Worker, publication, ES, and Milvus state before claiming end-to-end success.
12. Retry only classified transient failures. Path, permission, format, schema, and other deterministic business validation failures must become terminal structured failures without automatic replay.
13. Every terminal path must converge TaskPlan status, deliverable status, progress stage, checkpoint state, structured error, and SSE output. React must receive the TaskPlan ID and stable error code without inferring state from natural-language text.

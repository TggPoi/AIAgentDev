# React Agent Frontend Engineering Rules

This file defines the repository-specific implementation rules for the React workspace. It supplements higher-level coding instructions; it does not replace them.

## 1. Required Reading and Source of Truth

Before planning, creating dependencies, or changing frontend behavior:

1. Read `docs/SPEC.md` completely.
2. Read `docs/ARCHITECTURE.md` completely.
3. Read `docs/DEVELOPMENT.md` for the verified toolchain and commands.
4. Read `docs/features/README.md`.
5. Read every `docs/features/<feature>/feature.md` affected by the task.
6. Inspect the existing implementation, types, tests, package manifest, and lock file when they exist.

Treat the current specification and the relevant feature document as the product contract. Treat the current backend route, schema, OpenAPI, and tested behavior as the network-contract truth.

If code, frontend documentation, and backend behavior conflict:

- stop before changing public behavior;
- report the exact conflict and its evidence;
- update the specification or backend contract only after the user confirms the intended behavior;
- never hide a backend gap by calling a development or compatibility endpoint.

Honor the status gate at the top of `docs/SPEC.md`. The development environment may be maintained because the user explicitly authorized it, but this does not authorize business features. Do not implement pages, API clients, or feature behavior until the user explicitly approves the corresponding scope.

## 2. Locked Product Boundaries

- The only React RAG / Agent question-answering endpoint is `POST /rag/chat/stream/events`.
- Do not call `/rag/chat`, `/rag/chat/stream`, `/rag/search`, `/rag/search/stream`, or `/nl2sql/query` from the React application.
- The frontend does not expose a Classic, LangGraph, or pipeline-provider selector. The active business provider is `rag_agent`; Agent Router states are backend internals.
- Do not add document upload, GitLab Source administration, ingestion operations, RAG Eval, Debug Trace, LangSmith, or API Key management unless the user explicitly expands the approved scope and the specifications are updated first.
- NL2SQL and Web Search are capabilities inside the unified chat experience, not separate question-answering applications.
- Do not begin an adjacent feature merely because its backend endpoint exists.

## 3. Initial Implementation Order

After the documentation gate is approved, build in the following dependency order unless a narrower user task requires only one already-supported slice:

1. Vite + React + TypeScript application and test tooling.
2. Shared HTTP client, error model, auth lifecycle, SSE parser, and test fixtures.
3. Application shell, routes, route guards, and authentication pages.
4. Conversation catalog and RagAgent chat.
5. TaskPlan recovery/control and knowledge documents.
6. User management and cross-department document grants.
7. NL2SQL and Web Search presentation refinements.
8. Cross-feature integration, accessibility, responsive behavior, and browser-flow verification.

Complete and verify one coherent slice before starting the next. Do not scaffold empty speculative features.

## 4. Architecture and Module Boundaries

Use the architecture defined in `docs/ARCHITECTURE.md`:

- React + TypeScript + Vite.
- React Router for routes and guards.
- TanStack Query for ordinary server state and mutations.
- Native `fetch` + `ReadableStream` for POST SSE.
- Feature-local reducers for ordered stream state.
- Vitest, React Testing Library, and MSW for automated tests.

Keep these responsibility boundaries:

- `src/api/` owns base URL handling, authorization, JSON/Blob responses, error translation, refresh coordination, AbortSignal, and SSE framing.
- `src/features/<feature>/api` owns typed business endpoint functions.
- Feature models/reducers translate transport data into UI state.
- Route pages compose features; they do not duplicate protocol, token, ACL, or TaskPlan logic.
- Shared components contain behavior that is genuinely reused across features and remain business-neutral.

Do not introduce a global state library, provider abstraction, generated plugin system, or generic repository layer without a demonstrated need that the approved architecture does not satisfy.

## 5. Authentication and HTTP Rules

- Keep the access token in memory only.
- Under the current JSON token contract, keep the refresh token only in the current tab's `sessionStorage`; do not use `localStorage`.
- Never put passwords or tokens in URLs, logs, analytics, error messages, snapshots, or test output.
- Use one shared refresh Promise when concurrent requests receive `401`. Replay each original request at most once.
- Login, refresh, logout, and already-replayed requests must not enter recursive refresh handling.
- On refresh failure or identity change, abort active streams and clear all private Query Cache before routing to login.
- Parse JSON, empty `204`, text/Markdown, and Blob responses through explicit client methods.
- Pass AbortSignal through every cancellable request.

Use the backend as the final error authority:

- `401`: try the single shared refresh only when eligible; otherwise leave the authenticated state.
- `403`: the authenticated user cannot perform the action.
- `404`: treat the resource as unavailable; do not infer whether it is absent or hidden by authorization.
- `409`: refresh the affected server state and present the conflict; do not overwrite it optimistically.
- `422`: map validation details to the corresponding fields when safe.

## 6. Structured SSE Rules

Implement `POST /rag/chat/stream/events` with `fetch` and a reusable streaming parser. Do not use `EventSource`.

The parser must correctly handle:

- arbitrary byte/chunk boundaries;
- LF and CRLF separators;
- multiple frames in one chunk;
- frames split across chunks;
- multiple `data:` lines and comment lines;
- a final incomplete buffer without silently treating it as success.

Every public event payload must be associated with `contract_version: "1.0"` and a request ID. The stream layer must:

- route known events to typed reducers;
- retain unknown events as safe, read-only timeline entries for forward compatibility;
- isolate events by the active request ID;
- ignore late events from aborted or superseded requests;
- treat `done` as the only successful terminal event;
- treat `error` as a failed terminal event and not wait for `done` afterward;
- treat EOF without a terminal event as `interrupted`;
- distinguish browser abort from server-side TaskPlan cancellation.

Do not automatically retry a chat POST or TaskPlan execution stream after a network failure. Reload persisted conversation or TaskPlan state first to avoid duplicate turns and tool execution.

## 7. Authorization and Data Isolation

- Never calculate effective authorization in the browser.
- `/auth/me` provides identity facts; `/auth/capabilities` controls discoverability and route experience. Neither replaces backend authorization on the actual request.
- Do not submit `allowed_departments`, `allowed_users`, user-derived document IDs, internal scoped session IDs, or other permission scope fields.
- Include the authenticated user boundary in private cache ownership. Clear caches when the user changes.
- A user can read all documents belonging to their own departments. Cross-department access requires an active grant for the exact `doc_id` from the owning department manager or an administrator.
- A document grant is read-only and does not imply target-department membership or access to neighboring documents.
- Do not cache a client-side allowlist and use it to authorize document display, download, or source navigation.
- Department managers only manage employees in their server-defined primary-department scope. Build forms from `/admin/access/catalog`; do not hard-code assignable roles or permission codes.

Capability checks may hide menus and disable actions, but direct routes and mutations must still handle server rejection safely.

## 8. Feature-Specific Invariants

### Conversations

- Use external `session_id` in routes and requests; never expose or construct a backend scoped conversation ID.
- Key conversation and message caches by authenticated user and external session ID.
- Preserve backend cursor order and deduplicate by stable IDs; do not replace keyset pagination with client sorting.
- After every stream terminal or interruption, refetch the affected conversation and message history to converge on persisted state.
- The backend currently does not guarantee automatic replacement of an explicitly created default title with the first question; do not promise this behavior in the UI.

### RagAgent Chat

- Allow only one active stream per conversation in the initial implementation.
- Keep pending UI messages distinguishable from persisted history.
- Render Markdown through a sanitized path with raw HTML disabled.
- Navigate `source_type=knowledge_document` by stable `doc_id` only.
- Open `source_type=web` only from the backend `href`, after a frontend HTTP(S) check, with `noopener,noreferrer`.
- Never construct an external URL from arbitrary metadata.

### TaskPlan

- Determine buttons from structured `status`, `task_kind`, and the latest backend response, never from natural-language messages.
- Preserve one `Idempotency-Key` for transport retries of one user action. Generate a new key only for a new deliberate action.
- A stopped confirmation stream does not mean the server task stopped; refetch detail before showing a final state.
- On `409`, refetch and recalculate allowed controls.

### Knowledge Documents

- Use authenticated fetch for downloads, create a short-lived object URL, and revoke it after use.
- Do not navigate directly to protected download URLs or private GitLab locations.
- Render according to backend `render_mode`; display truncation and parser warnings.
- Keep hidden and missing documents indistinguishable in the UI.

### User Management and Grants

- Build account, department, role, and permission choices from the server catalog.
- Send complete access snapshots to the PUT endpoint; do not emulate atomic replacement with multiple requests.
- Do not optimistically apply disable, password reset, grant creation, or grant revocation.
- Password fields are transient and must be cleared after submission.
- Grant targets use an exact username or email. Do not build an unapproved cross-department user directory.

### NL2SQL and Web Search

- Omit both `dataset_id` and `nl2sql_action`, or send both. Do not allow an arbitrary Dataset ID.
- Treat generated SQL as read-only display text; never add an execute-edited-SQL action.
- Render result cells as text and respect backend truncation and warnings.
- Persisted conversation history restores the NL2SQL question, summary, and terminal state, not the complete result table.
- Keep `allow_direct_web` and `allow_web_fallback` as distinct meanings.
- Never send sensitive Dataset results, internal document bodies, ACLs, or permission facts to Web Search from frontend composition.

## 9. UI, Accessibility, and Security

Every asynchronous page must distinguish initial loading, ready, empty, error, and background refreshing states. Do not replace blocking errors with transient toast messages.

- Lock destructive or high-risk submit buttons while pending and require explicit confirmation where specified.
- Preserve keyboard operation, visible focus, dialog focus return, labels, and meaningful status announcements.
- Do not use raw HTML rendering for user, model, document, SQL, or error content.
- Do not expose stack traces, prompts, credentials, private service URLs, or unsanitized backend payloads.
- Display safe request IDs for support diagnostics when available.
- Keep desktop and narrow-screen core flows functional.

## 10. Testing and Verification

For each behavior change:

1. Add or update the smallest relevant test first when practical.
2. Verify pure parsers and reducers with deterministic fixtures.
3. Verify component loading, empty, error, permission, conflict, submit, abort, and terminal states.
4. Use MSW for HTTP/SSE integration; do not require a live model for deterministic frontend tests.
5. Run focused tests before the broader suite.
6. Run TypeScript checks, lint, tests, and production build when configured.
7. Inspect the final diff for unrelated changes and specification drift.

The minimum critical contract coverage includes:

- concurrent `401` single-flight refresh;
- refresh failure and private-cache clearing;
- SSE arbitrary chunking, known/unknown events, request isolation, `done`, `error`, interruption, and abort;
- same-session isolation between users;
- hidden navigation plus backend `403/404` handling;
- TaskPlan idempotency and `409` convergence;
- authenticated document Blob download and URL cleanup;
- exact-document grant creation and revocation behavior.

Do not claim a command, build, browser flow, or test passed unless it was actually executed successfully.

## 11. Documentation and Contract Changes

- Keep `docs/SPEC.md`, `docs/ARCHITECTURE.md`, and the affected feature document aligned with approved behavior.
- If implementation requires a changed product rule, public route, schema, SSE event, security boundary, dependency, or storage decision, update the documentation as part of the same approved change.
- Do not mark planned behavior as implemented.
- Do not copy the backend TodoList into this repository. The backend source and its `docs/BACKEND_INTERFACE_TODO.md` remain the backend implementation record.
- Preserve the feature directory names and one-feature-per-directory structure.

## 12. Completion Checklist

Before handing off a frontend change, confirm:

- the documentation gate was satisfied;
- only approved endpoints and features were used;
- authentication, authorization, error, cancellation, and terminal-state boundaries are covered;
- no permission or URL was inferred from unsafe client data;
- focused tests and configured static/build checks were run;
- no secrets or sensitive data entered output, code, fixtures, snapshots, or logs;
- the final diff contains no unrelated edits;
- any remaining unverified behavior is stated explicitly.

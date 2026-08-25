# React Agent Frontend Engineering Rules

This file contains repository execution rules. Product behavior belongs in `docs/SPEC.md` and the relevant feature specification; implementation structure and protocol strategy belong in `docs/ARCHITECTURE.md`.

## 1. Required Reading and Authority

Before planning dependencies or changing frontend behavior:

1. Read `docs/SPEC.md` completely.
2. Read `docs/ARCHITECTURE.md` completely.
3. Read `docs/DEVELOPMENT.md` for the verified toolchain and commands.
4. Read `docs/features/README.md`.
5. Read every affected `docs/features/<feature>/feature.md`.
6. Inspect the existing implementation, tests, types, package manifest and lockfile.

If `docs/exec-plans/active/` contains an active execution plan:

- read it before planning, implementing or continuing frontend work;
- treat the execution plan together with current Git and repository state as the implementation-progress source of truth, never conversation history alone;
- when context was compressed, the session changed or progress is uncertain, follow that plan's Context Recovery Protocol before continuing;
- update the plan promptly after every meaningful checkpoint or completed Slice.

Use this source-of-truth order:

```text
approved product requirement
        ↓
docs/SPEC.md and the relevant feature specification
        ↓
docs/ARCHITECTURE.md
        ↓
current frontend implementation
```

For network behavior, the current backend Route, Pydantic Schema, OpenAPI and tested implementation are authoritative. If those sources conflict, stop before changing public behavior, report exact evidence and record an unresolved backend contract gap. Do not guess or hide a gap by calling a development or compatibility endpoint.

## 2. Status and Scope Gates

- Honor the status gate in `docs/SPEC.md`. A verified development environment does not authorize business implementation.
- Do not add or begin a feature merely because a backend endpoint exists. Scope changes require explicit user approval and a specification update first.
- The only React RAG / Agent question-answering endpoint is `POST /rag/chat/stream/events`.
- Do not call `/rag/chat`, `/rag/chat/stream`, `/rag/search`, `/rag/search/stream` or `/nl2sql/query` from React.
- Do not expose Classic, LangGraph or pipeline-provider selection. Follow the approved scope exclusions in `docs/SPEC.md`.
- Complete and verify one coherent approved slice before starting the next; do not scaffold speculative feature code.

## 3. Architecture and Contract Discipline

- Read and follow `docs/ARCHITECTURE.md`; do not duplicate protocol or business rules in route pages or feature components.
- `AuthProvider` is the single owner of the authentication bootstrap snapshot (`CurrentUser` and `Capabilities`) as well as the token lifecycle. Do not duplicate that snapshot in TanStack Query. TanStack Query owns other ordinary business server state.
- Components must not define duplicate backend DTOs. Use the documented generated HTTP transport types, centralized SSE public-event contracts and feature adapters.
- Generated contract files must never be edited manually.
- Route pages live in `src/pages/` and only compose features. Do not create feature-local `pages/` directories.
- Do not introduce a global state library, a provider abstraction, a generic repository layer, a UI library or an E2E framework without an approved architecture/dependency decision.
- Follow the relevant feature specification for all detailed authentication, conversation, TaskPlan, document, administration, NL2SQL and Web Search rules.

## 4. Security Baseline

- Never put passwords, tokens, credentials, prompts, ACLs, sensitive Dataset values or private service URLs in URLs, logs, analytics, errors, fixtures, snapshots or browser storage not explicitly approved by the architecture.
- Never calculate effective authorization in the browser. Capability checks only control discoverability; the backend authorizes every request.
- Treat `visibility=public` knowledge documents as public-area documents readable by every authenticated user without a grant. Exact cross-department grants apply only to non-public documents; follow the relevant feature specifications.
- Never submit client-derived permission scopes, internal scoped session IDs or arbitrary document/Dataset identifiers outside the documented request contract.
- Unknown SSE payloads must never be rendered, logged, cached or persisted verbatim. Production code may retain only explicitly allowlisted safe metadata defined in `docs/ARCHITECTURE.md`.
- Do not render raw HTML or construct external URLs from arbitrary metadata.
- Login return paths must pass the internal-relative-route validation defined in the authentication and application-shell specifications.

## 5. Implementation and Verification

- Make the smallest complete change for the approved slice and preserve documented module seams.
- Add or update the smallest relevant deterministic test when behavior changes. Use MSW and fixtures; do not require a live model.
- Run focused tests first, then configured lint, typecheck, tests and production build in proportion to the change.
- Critical browser flows are manual smoke verification until an E2E framework is explicitly approved; do not add Playwright or Cypress implicitly.
- Inspect the full diff before handoff. Do not claim a command or browser flow passed unless it was actually executed successfully.
- Preserve user changes and never expose secrets in command output or committed files.

## 6. Documentation Rules

- Keep `docs/SPEC.md`, `docs/ARCHITECTURE.md` and every affected feature specification aligned with approved behavior and the verified backend contract.
- Do not mark planned behavior as implemented. Record unresolved contract gaps with evidence, impact and the recommended backend change without modifying the backend unless separately authorized.
- Do not copy the backend TodoList into this repository. Preserve the one-feature-per-directory documentation structure.
- Do not remove or replace an approved product-level visual requirement when regenerating or restructuring specification documents. Changing the approved clean, minimal, blue-and-white direction is a product requirement change and requires explicit user confirmation.

## 7. Completion Checklist

Before handing off a frontend change, confirm:

- the documentation and scope gates were satisfied;
- only approved endpoints and features were used;
- authentication, authorization, error, cancellation and terminal-state seams remain correct;
- contract types and feature models have one documented source of truth;
- focused and configured checks were actually run where applicable;
- no secrets or unsafe payloads entered output, code or tests;
- the final diff contains no unrelated changes;
- remaining contract gaps and unverified behavior are stated explicitly.

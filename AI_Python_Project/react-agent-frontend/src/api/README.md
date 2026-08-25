# API module boundaries

- `generated/backend-schema.ts` is generated from `contracts/backend-openapi.json`; never edit it manually.
- Feature API modules select request/response DTOs from the generated `paths`, `operations`, and `components` types.
- A Feature adapter is the only place that may convert a generated HTTP transport DTO into a Feature Domain/UI Model. Components must consume the Domain/UI Model and must not redeclare backend DTOs.
- `http-client.ts` owns base URL resolution, Bearer injection, request IDs, safe error projection, response decoding, and the pre-stream HTTP boundary. Authentication state and refresh coordination remain owned by the future `AuthProvider`.
- `sse/` owns byte framing, the shared public envelope, request isolation, safe unknown-event projection, and terminal classification. Chat and TaskPlan reducers own their separate business state transitions.

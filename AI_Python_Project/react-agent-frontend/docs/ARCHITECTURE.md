# React RAG 工作台架构

> **状态：已批准的实现架构基线。** 本文约束 Initial React frontend 的模块、状态与协议策略；实际实施进度、checkpoint 和当前 Contract Gap 以 active Execution Plan、Git、Repository 与 Tests 为准。

## 1. 技术选型与模块原则

- React + TypeScript + Vite。
- React Router：页面路由、登录保护和 capability 入口体验。
- TanStack Query：除认证 Bootstrap State 外的普通 HTTP Server State、缓存、失效和 mutation 状态。
- 原生 `fetch` + `ReadableStream`：POST SSE；不使用只支持 GET 的 `EventSource`。
- Feature 本地 reducer：对话流、TaskPlan 流等有序交互状态。
- Vitest + React Testing Library + MSW：单元、组件和网络契约测试。

共享 HTTP、认证生命周期、SSE framing 和 UI Primitive 都应形成深模块：调用方只学习一个稳定 Interface，复杂性集中在模块内部。首期不引入全局状态框架、通用 repository 层、运行时 provider 抽象或插件系统。

## 2. Contract Type 策略

网络契约类型与前端展示模型分层：

```text
FastAPI Pydantic Schema
        ↓
FastAPI OpenAPI Snapshot
        ↓
generated TypeScript Transport DTO
        ↓
Feature Adapter / Mapper
        ↓
Frontend Domain / UI Model
```

### 2.1 普通 HTTP

- Phase 1 使用 `openapi-typescript` CLI 生成普通 HTTP Transport Type；这是类型生成工具，不替换共享 `fetch` client。
- 提交的后端 OpenAPI 快照放在 `contracts/backend-openapi.json`；生成文件放在 `src/api/generated/backend-schema.ts`。
- 生成文件只表示 transport DTO、path、query、request body 和 response schema，禁止手工编辑。
- Feature API 从生成文件引用 operation/schema 类型；Feature adapter 把 DTO 转为页面需要的 Domain/UI Model。Component 不得自行声明重复 DTO。
- 开始首个 API 代码切片时，必须为 `openapi-typescript` 选择并锁定与当前 Node 兼容的精确版本，更新 lockfile 和 `docs/DEVELOPMENT.md`；本轮文档任务不安装依赖。
- 后端契约变化后，先重新导出 OpenAPI 快照，再生成 TypeScript 类型，并运行 contract check。生成结果有未提交差异时检查失败；不得用手改 generated file 消除差异。
- OpenAPI 只证明已声明内容；runtime header、SSE wire frame 和业务错误仍需由后端契约测试与前端 MSW fixture 共同验证。

### 2.2 结构化 SSE

普通 OpenAPI 生成不能替代 SSE Public Event Contract。聊天流与 TaskPlan confirm stream 的 OpenAPI 都声明通用逻辑帧，runtime 的每个公开 event payload 都包含统一的 `contract_version` 和 `request_id`，因此：

- 所有已确认的 Public Event 在 `src/api/sse/public-events.ts` 集中定义 discriminated union；Feature 不得各写一套 backend event DTO。
- `src/api/sse/` 只负责 wire framing、公共 envelope 校验、安全 unknown-event 投影和终止语义；Feature reducer 负责把已验证事件映射为 UI state。
- Public Event union 必须与后端 `rag_stream_schema.py`、TaskPlan 公共事件契约及固定 MSW fixtures 同步验证。
- 后端未形成稳定公共 schema 的新事件不得凭当前内部 payload 推导长期前端 DTO；先记录 contract gap 并等待契约确认。

## 3. 目标目录与 Page Ownership

```text
src/
├─ app/                    # Router、Provider、启动流程和顶层错误边界
├─ api/
│  ├─ generated/          # OpenAPI 生成的 HTTP transport types
│  └─ sse/                # SSE framing 与集中 Public Event contract
├─ components/
│  └─ ui/                 # 统一 Shared UI Primitives
├─ features/
│  ├─ auth/
│  ├─ conversations/
│  ├─ chat/
│  ├─ task-plans/
│  ├─ knowledge-documents/
│  ├─ user-management/
│  ├─ document-grants/
│  ├─ nl2sql/
│  └─ web-search/
├─ layouts/                # 登录布局、工作台布局
├─ pages/                  # 唯一路由装配层
├─ styles/                 # 全局入口、tokens 与共享布局规则
├─ test/                   # MSW、fixtures、render helpers
└─ types/                  # 真正跨 feature 的稳定前端类型
```

`src/pages/` 是唯一 Page Ownership，只组合 layout 与 feature module，不承载协议、token、ACL 或业务 mutation。Feature 内只在真实需要时建立 `api`、`components`、`hooks`、`model`；不得创建 `features/<feature>/pages`。

## 4. 状态所有权

| 状态 | 唯一所有者 | 规则 |
| --- | --- | --- |
| access token、refresh lifecycle、`CurrentUser`、`Capabilities`、`authStatus`、refresh coordination、logout / identity-change lifecycle | AuthProvider | `/auth/me` 与 `/auth/capabilities` 是 Authentication Bootstrap State，不进入 Query Cache |
| 其他普通业务 Server State | TanStack Query | 会话、消息、TaskPlan、文档、用户、grant、Dataset 等 |
| 当前 SSE 请求 | Chat / TaskPlan reducer | 处理顺序、终止、取消和迟到事件 |
| 页面筛选与选中实体 | URL search params / route params | 支持刷新、分享和前进后退 |
| 表单草稿 | 表单局部状态 | 不污染全局事实 |

禁止 `/auth/me -> TanStack Query -> AuthProvider` 的复制链路。Application Shell、authenticated guard 与 capability guard 全部读取 AuthProvider 的同一认证快照。

AuthProvider 暴露一个 `reloadIdentitySnapshot()` Interface，并行读取 `/auth/me` 与 `/auth/capabilities`，只有两者都成功时才原子替换当前快照。后端 `UserCapabilitiesResponse` 不含 `user_id` 或其他 actor identity 字段，因此不得编造 `me.user_id === capabilities.user_id` 校验；身份事实来自当前 auth/token lifecycle 与 `/auth/me.user_id`。

AuthProvider 同时维护单调递增的 `authGeneration`（或等价 reload epoch）。每次 deliberate `reloadIdentitySnapshot()` 开始时先推进 generation，并让本次 reload 捕获该值；两个响应都成功后，只有 captured generation 仍等于当前 generation，且 `/auth/me.user_id` 仍符合当前 auth lifecycle 时，才可原子发布完整 `CurrentUser + Capabilities`。较新的 reload 开始、logout、身份切换、refresh failure 或 token/auth lifecycle reset 都必须先推进 generation，使所有旧的 in-flight reload 结果失效并在返回时直接丢弃。规则是 **latest valid authentication generation wins**，不是 last network response wins。

原子发布与 stale-response rejection 是两个独立约束：原子发布防止用户与能力只更新一半，generation 校验防止较旧的完整快照覆盖较新的完整快照。可能影响当前登录用户身份或能力的 mutation 完成后必须调用该 Interface；管理其他用户只失效相应业务 Query。若当前 generation 的 `/auth/me.user_id` 意外不同于该 generation 的 active identity，或发生认证失败、refresh 失败，先使旧 generation 失效，再 abort 活动流、清空全部私有 Query Cache 并进入匿名状态；明确的登录/身份切换则先建立新 generation，再执行该身份的 Bootstrap。非认证类临时失败不得发布半份新快照；仅当该请求仍属于当前 generation 时保留旧快照并标记 stale，实际请求继续以后端授权为准。

## 5. 启动、Token 与身份生命周期

1. 从当前标签页 `sessionStorage` 恢复 refresh token；access token 始终只在内存。
2. 必要时调用 `/auth/refresh` 取得轮换后的 token pair。
3. AuthProvider 并行读取 `/auth/me` 与 `/auth/capabilities`，原子发布 Bootstrap Snapshot。
4. Bootstrap 完成前显示启动屏，不短暂渲染受保护页面。
5. 恢复失败时清空本地身份、活动流和私有 Query Cache，进入 `/login`。

并发请求收到 `401` 时共享一个 refresh Promise；等待者在成功后各自最多 replay 原请求一次。登录、refresh、logout 和已经 replay 的请求不得递归刷新。

当前 refresh token 存于 `sessionStorage` 只是兼容后端 JSON Token Contract 的技术债务，不是最终生产安全形态。目标是后端支持 `HttpOnly + Secure + appropriate SameSite` Cookie 后，由前后端共同迁移 Auth Lifecycle。React 不能在后端尚无 Cookie Contract 时单方面切换。

## 6. 共享 HTTP 与 Streaming Transport

`src/api/http-client.ts` 负责基础 URL、Bearer、`Content-Type`、`X-Request-ID`、统一 `ApiError`、single-flight refresh、JSON / text / Markdown / empty / Blob 响应和 AbortSignal。Feature API 不重复 token 或状态码逻辑。

Streaming Transport 复用相同的 authorized fetch seam，并明确分为两个阶段：

### 6.1 阶段一：尚未进入成功 Streaming Response

- Bearer、`X-Request-ID`、AbortSignal 和 error mapping 与普通 HTTP 完全共用。
- `401` 在符合 refresh 条件时进入共享 single-flight refresh；成功后原 POST 最多 replay 一次。
- replay 必须保留同一个 `X-Request-ID`；TaskPlan 同一次动作还必须保留同一个 `Idempotency-Key`。
- `403 / 404 / 409 / 422 / 5xx` 转为 `ApiError`，不进入 SSE parser，也不自动 replay。
- 只有成功状态且响应的**已解析 media type** 为 `text/event-stream` 后才取得 reader；不得对完整 `Content-Type` header 做严格字符串等值比较。`text/event-stream` 和带合法参数的 `text/event-stream; charset=utf-8` 都接受，`application/json` 等其他 media type 作为 pre-stream failure，不进入 SSE parser。

当前后端在构造两个 `StreamingResponse` 前完成认证、请求校验和入口授权，因此 pre-stream `401/403/409/422` 可按以上规则处理。

### 6.2 阶段二：已经进入 Streaming Response

- 一旦开始读取 SSE，网络断开或 EOF without terminal event 转为 `interrupted`。
- 绝不自动 replay POST；先重新读取 conversation messages / list 或 TaskPlan detail，收敛到服务端持久化状态。
- 后端 `error` event 是失败终态，之后不等待 `done`；`done` 是唯一成功终态。
- 浏览器 Abort 是本地 `cancelled`，不等价于服务端 TaskPlan cancellation。TaskPlan 真正取消必须调用控制接口并 refetch detail。

SSE Transport 不实现第二套 refresh 逻辑；它只在共享 authorized fetch 成功后接管 body framing。

## 7. Request ID 与聊天 SSE 隔离

对 `POST /rag/chat/stream/events`，当前后端支持并明确采用同一 ID：

```text
frontend-generated X-Request-ID
        = response X-Request-ID
        = every chat SSE data.request_id
```

- 前端在一次新的 deliberate stream action 开始时用 `crypto.randomUUID()` 生成 ID，并在 reducer 进入 `connecting` 前绑定。
- pre-stream `401` refresh replay 复用该 ID；用户主动重新提交是新 action，应生成新 ID。
- 每个已知聊天事件都必须含 `contract_version: "1.0"` 且 `request_id` 等于当前 action ID。缺失或不匹配属于协议错误：不进入业务 reducer，当前流转为可见的 `interrupted` 并 refetch 持久化状态。
- abort 或 supersede 后保留已关闭 action ID，迟到事件直接丢弃。

后端证据是 `RequestIdMiddleware` 接收客户端 `X-Request-ID` 并原样写回响应，`rag_chat_routes.format_sse_event()` 又把同一 request context 注入 payload；聊天 OpenAPI 也声明了两者对齐。

TaskPlan `confirm/stream` 使用同一公共 envelope：前端生成的 `X-Request-ID`、response `X-Request-ID` 与每个 TaskPlan event 的 `data.request_id` 必须一致，`contract_version` 必须为 `"1.0"`。其业务事件仍进入 TaskPlan 自己的 discriminated union 和 reducer，不得误用聊天业务事件模型。

## 8. Known / Unknown SSE Event 安全策略

```text
Known Public Event
        ↓
central discriminated union
        ↓
typed feature reducer
        ↓
normal UI

Unknown Event
        ↓
discard raw payload immediately
        ↓
allowlisted safe projection only
```

Unknown Event 的 Production 投影最多包含：

- event type；
- 已通过格式与当前 action 校验的 request ID（若该流契约提供）；
- 前端接收时间；
- 通用“当前前端版本暂不支持此事件”状态。

未知 payload 不得被 `JSON.stringify(data)` 展示，不得原样进入 Timeline、console、日志、Query Cache、持久化存储、错误报告或测试 snapshot。Prompt、Tool Arguments、Credentials、ACL、内部 URL、Trace、敏感 Dataset 数据和未经审核的新字段一律丢弃。开发环境诊断也只能使用同一 allowlist，不保留 raw payload。

## 9. Query Key 与服务端收敛

所有私有 Query Key 以当前 authenticated user boundary 开头。Conversation 只存在两个服务端读取事实：

```text
[userBoundary, "conversations", listParams]
[userBoundary, "conversation-messages", sessionId, pageParams]
```

后端没有 `GET /conversations/{session_id}`。选中会话摘要只能从 conversation list 派生，不得建立暗示独立 endpoint 的 `conversation-detail` Query。

- Rename 成功后失效 conversation list；响应本身可更新已存在的列表项，但仍以 refetch 顺序为准。
- Stream `done`、`error`、`interrupted` 或浏览器 abort 后统一失效当前 conversation messages 与 conversation list。
- Delete 成功后移除该 session 的 message cache 并失效 conversation list。
- TaskPlan mutation 或流终止后 refetch detail/list；`409` 先 refetch 再重算允许操作。

## 10. Feature 与 Endpoint 映射

| Feature | 普通 HTTP | 流式接口 |
| --- | --- | --- |
| Auth | `/auth/login`、`/auth/refresh`、`/auth/logout`、`/auth/change-password`、`/auth/me`、`/auth/capabilities` | 无 |
| Conversations | `/conversations`、`/conversations/{session_id}/messages` | 消息由聊天流写入 |
| Chat | 无独立非流式调用 | `POST /rag/chat/stream/events` |
| TaskPlan | `/agent/task-plans*`；首期 React 不使用非流式 `/confirm` | 首期确认只使用 `/{id}/confirm/stream` |
| Documents | `/knowledge/documents*` | 无 |
| Users | `/admin/access/catalog`、`/admin/users*` | 无 |
| Grants | `/admin/document-access/grants*` | 无 |
| NL2SQL | `/nl2sql/datasets` | 复用聊天流；不调用 `/nl2sql/query` |
| Web | 能力来自 AuthProvider Bootstrap Snapshot | 复用聊天流 |

后端存在的 `POST /agent/task-plans/{id}/confirm` 保留为真实后端接口，但不属于 Initial React confirmation flow；Codex 不得自行决定在两个确认接口之间切换。

## 11. 路由、Capability 与 Return Path

Authenticated guard 与 capability guard 分离。Capability 只控制 discoverability 和 route experience，不替代后端授权；直接访问和 mutation 必须安全处理 `403/404`。

Login return path 只能是当前 React 应用内部 relative route：

- 必须以单个 `/` 开头；拒绝绝对 URL、scheme URL、`//example.com`、反斜杠变体和其他 Origin。
- 解析后 Origin 必须与当前应用一致，且只保留 pathname、search 与 hash 作为 React Router 导航目标。
- 不得把原始 return path 传给 `window.location`。
- 校验失败或目标为空时，登录后回退 `/chat`。

身份或 capabilities 原子更新后立即重算导航；当前 route 已失去 discoverability 时进入安全入口并显示说明，真实资源是否可用仍以后端响应为准。

## 12. Styling 与 Shared UI Strategy

UI 实现必须保持 `docs/SPEC.md` 的产品级视觉方向：**clean, minimal, blue-and-white**。技术实现采用：

- CSS Modules：Feature 与 Shared Primitive 的局部样式。
- 全局 CSS Custom Properties：由 `src/styles/tokens.css` 统一定义基础 tokens，`src/styles/index.css` 作为全局入口。
- 首期不引入完整 UI Component Library，也不引入 Tailwind。需要新增 UI Library 时必须先形成明确的架构、可访问性与依赖决策。
- `src/components/ui/` 统一拥有 Button、Input、Form Control、Dialog、Drawer、Sidebar、Table、Toast、Skeleton、Markdown Viewer、Empty State 和 Error State 等 Shared Primitive。Feature 不得重复实现另一套基础控件。

最低限度 token 包含：

```text
Primary
Background
Surface
Border
Text Primary
Text Secondary
Success
Warning
Error
Focus
Typography
Spacing
Radius
Shadow
```

具体 Hex 色值在首个 UI 实现切片确定，但必须由共享 token 一次定义，并满足 `Primary visual identity = Blue + White`。组件库默认 Theme 或 Feature 局部颜色不能建立新的主色体系；状态色只能表达语义。

首期布局断点统一为 `compact < 768px`、`standard 768px–1199px`、`wide >= 1200px`。断点只在共享 layout/style 规则中维护；Feature 的真实例外必须复用这三个区间并在对应 specification 说明。字体、间距和视觉层级同样由全局 token 控制。

## 13. 通用安全约束

- 不记录 token、密码、原始未知事件、查询敏感结果或原始错误响应中的秘密。
- 不从 JWT claim、capability 或前端选项推导 ACL。
- Markdown 走安全渲染，禁用 raw HTML 和脚本 URL。
- 外链只读取后端 `RagSource.href`，再次校验无凭据 HTTP(S)。
- 文档下载使用认证 fetch 和短生命周期 object URL，用毕 revoke。
- `404` 不区分资源不存在与无权访问。
- destructive mutation 不做乐观更新，以服务端响应与 refetch 为准。
- Async 页面区分 initial loading、ready、empty、error 和 background refreshing；阻断错误不能只用 Toast。

## 14. 测试与 Browser Flow

1. 纯函数：SSE framing、Public Event 校验、安全 unknown projection、reducer、游标、错误与 return-path 校验。
2. Feature 组件：loading、empty、error、permission、conflict、submit、abort 和 terminal state。
3. MSW 集成：Auth Bootstrap、并发 `401`、identity reload generation/stale rejection、pre-stream error 与参数化 SSE media type、聊天终止、TaskPlan 控制、Blob 下载和身份切换。
4. 关键浏览器流程目前是 **manual smoke verification**：登录到对话、历史恢复、文档读取、主管授权和管理员用户管理。

当前没有 Playwright/Cypress 等 E2E Framework。自动 E2E 需要用户批准新的架构与依赖决策后再增加；“browser-flow verification”不得被解释为自动安装 E2E 工具。

## 15. 已确认的后端契约

### 15.1 TaskPlan confirm stream 公共事件 envelope

`POST /agent/task-plans/{id}/confirm/stream` 已为每个公开 payload 注入 `contract_version: "1.0"` 与 request-context `request_id`；OpenAPI 200 response 已声明 `text/event-stream` 逻辑帧和 `X-Request-ID`。前端可执行第 7 节的统一 request isolation，但聊天与 TaskPlan 仍保留各自的业务事件 union。

### 15.2 Knowledge download revision 与文件名响应头

`GET /knowledge/documents/{doc_id}/download` runtime 返回 `X-Source-Revision` 与 `Content-Disposition`；OpenAPI 已正式声明两个 response header 和 binary content，CORS 也暴露 `X-Request-ID`、`X-Source-Revision`、`Content-Disposition`。前端可以验证 detail/content/download revision 后再保存 Blob。

### 15.3 Public 文档访问语义

`visibility=public` 表示文档在授权语义上属于公共区域，不归属任何部门，所有已认证用户无需 grant 即可读取。部门归属和精确 grant 规则只约束非 public 文档：用户可读取所属部门文档，读取其他部门文档需要目标 `doc_id` 的 active grant。后端 `DocumentAccessPolicy` 先判定 public 的现有行为符合该产品规则，不是 contract gap。

# Initial React Frontend Execution Plan

## Status

Status: ACTIVE

Plan Approval: APPROVED BY USER ON 2026-08-25

Current Slice: 2 - Authentication Lifecycle and AuthProvider

Current Step: Slice 1 Gate verified; Slice 2 authentication authority and backend contract are being re-verified

Next Action: Read Authentication/Application Shell specs and verify current backend Auth Route, Schema, OpenAPI and deterministic tests

Blocking Issues:

- None

Last Updated: 2026-08-25 (Asia/Shanghai)

## Goal

按照已经批准的产品、架构和 Feature 规范，全量实现 Initial React frontend，并以可验证、可恢复、按业务边界提交的 Slice 推进。

本计划只管理实施顺序、当前状态、验证证据和上下文恢复，不修改产品 Scope。当前任务只建立计划与治理规则；在用户审核本计划前不得开始 Slice 1 或任何 React 业务编码。

最终结果必须覆盖：

- 身份认证与安全的 token/identity 生命周期；
- 应用工作台、路由与 capability discoverability；
- 会话、RAG/Agent 结构化对话与持久化收敛；
- TaskPlan、知识文档、用户管理与跨部门文档授权；
- NL2SQL 与 Web Search 在统一对话中的完整展示；
- 统一蓝白视觉、可访问性、响应式布局、错误状态和验证闭环。

## Sources of Truth

### A. Product / Behavior / Architecture Authority

产品行为与架构按以下 Authority 执行：

```text
用户当前明确批准的产品要求
        ↓
docs/SPEC.md + relevant Feature Spec
        ↓
docs/ARCHITECTURE.md
        ↓
Current frontend implementation
```

- `docs/SPEC.md` 与 relevant Feature Spec 共同描述批准的产品行为；二者若互相冲突，不得自行裁决，必须记录冲突并停止受影响实现。
- `docs/ARCHITECTURE.md` 约束实现结构与协议策略，不得覆盖批准的产品行为。
- `AGENTS.md` 是 repository execution rules 和 navigation，不是产品行为的 Source of Truth。
- 本 Execution Plan 管理 implementation progress 和 execution state，不得覆盖或修改 SPEC、Feature Specs 或 Architecture。
- `docs/DEVELOPMENT.md` 和 `docs/features/README.md` 分别提供已验证工具链命令与 Feature 文档导航；实施时仍必须按 `AGENTS.md` 的 Required Reading 规则完整读取。

### B. Network Contract Authority

网络契约的最终事实来源是：

```text
Backend Route
        ↓
Pydantic Schema
        ↓
OpenAPI
        ↓
Tested runtime behavior
```

若上述后端事实互相冲突，或与前端规格冲突：

- 停止受影响的公开行为实现；
- 记录精确 Evidence、Impact 和 Recommended Backend Change；
- 将问题标为 Contract Gap；
- 未经用户批准不得猜测、绕过、调用开发/兼容接口或修改后端。

### C. Implementation Progress Authority

实施进度的 Source of Truth 是：

```text
This Execution Plan
        +
Current Git status / diff / log
        +
Current repository code and tests
        +
Actually executed verification results
```

Conversation history 只能提供线索，不能单独证明当前进度。若本计划与 Repository/Git/Tests 冲突，以真实仓库状态为准，并先修正本计划。

## Implementation Slices

### Slice 0 - Execution Governance and Baseline

Status: COMPLETED

- [x] 完整读取 `AGENTS.md`、SPEC、Architecture、Development、Feature index 和全部十个 Feature specs。
- [x] 检查当前 Git branch/status 和最近 commits。
- [x] 检查当前 React 源码、测试基础设施和现有业务实现边界。
- [x] 检查 `package.json`、`pnpm-lock.yaml`、Node 和 pnpm 实际版本。
- [x] 运行当前 `pnpm check` 基线。
- [x] 创建本 Execution Plan。
- [x] 为 `AGENTS.md` 增加 active-plan 导航规则。
- [x] 用户审核并批准本 Execution Plan。
- [x] 创建仅包含批准文档、`AGENTS.md` 和本计划的 Git checkpoint。
- [x] 确认 checkpoint 后工作树干净，再将 Slice 0 标记为 COMPLETED。

Exit Evidence:

- 用户已明确批准计划；
- 文档 checkpoint 已创建；
- `git status --short --branch` 无意外修改；
- 本计划的 Current Slice 已切换到 Slice 1。

### Slice 1 - Contract Snapshot and Protocol Infrastructure

Status: COMPLETED

Goal: 建立普通 HTTP transport contract、共享 HTTP/error seam 和可独立验证的结构化 SSE protocol module，不实现 Feature 页面。

- [x] 重新读取 Architecture 第 2、6、7、8、13、14 节及 Chat/TaskPlan 契约。
- [x] 从当前后端真实 OpenAPI 导出 `contracts/backend-openapi.json`，记录导出命令和后端 commit。
- [x] 核对 Node compatibility，选择并锁定精确 `openapi-typescript` 版本；更新 package、lockfile 和 `docs/DEVELOPMENT.md`。
- [x] 生成 `src/api/generated/backend-schema.ts`，禁止手工修改 generated file。
- [x] 建立 HTTP transport DTO 到 Feature Domain Model 的唯一映射规则。
- [x] 实现共享 `ApiError` 与 JSON、empty 204、text/Markdown、Blob 响应解析。
- [x] 实现 base URL、Bearer callback seam、`X-Request-ID`、AbortSignal 和状态码映射；认证所有权仍留给 Slice 2 的 AuthProvider。
- [x] 实现 parsed `Content-Type` media-type 校验，接受合法参数化 `text/event-stream`。
- [x] 实现可复用 SSE framing parser：任意 byte/chunk、LF/CRLF、多 frame、多行 data、comment 和 incomplete EOF。
- [x] 集中定义 Public Event envelope、已批准 event union、安全 unknown-event projection 和 terminal semantics。
- [x] 增加 deterministic parser、media type、error mapping、unknown payload 丢弃和 OpenAPI drift 测试。
- [x] 完成 Slice Gate 并创建独立 Git checkpoint。

Explicit Boundary:

- 不实现 AuthProvider、登录页面、业务 Query 或 Chat reducer。
- 不调用 `/rag/chat`、`/rag/chat/stream`、`/rag/search*` 或 `/nl2sql/query`。

### Slice 2 - Authentication Lifecycle and AuthProvider

Status: IN_PROGRESS

Goal: 完成认证 Bootstrap Snapshot、token 生命周期、共享 refresh coordination 和认证页面，使后续 Feature 只依赖一个稳定 AuthProvider Interface。

- [ ] 读取 Authentication 与 Application Shell specs，并复核后端 Auth Route/Schema/OpenAPI/测试。
- [ ] 实现 access token memory storage 与 refresh token tab-scoped `sessionStorage` lifecycle。
- [ ] 实现 single-flight refresh；eligible 请求最多 replay 一次，login/refresh/logout/already-replayed 不递归刷新。
- [ ] 将共享 authorized fetch 与 AuthProvider token/refresh Interface 对接，不复制 token 或 refresh 状态。
- [ ] 实现 `CurrentUser + Capabilities` 原子 Bootstrap Snapshot，二者不进入 TanStack Query。
- [ ] 实现 `authGeneration`/epoch stale-response rejection，包括并发 reload、logout、identity change、refresh failure 和 lifecycle reset。
- [ ] 实现 identity change 时 abort 活动流并清空全部私有 Query Cache。
- [ ] 实现登录、启动恢复、注销、修改密码和安全 return-path 校验。
- [ ] 实现认证相关 loading/error/field validation，禁止密码和 token 泄漏。
- [ ] 增加并发 401、reload A/B 乱序、logout 后旧 reload、refresh failure、cache clear、return path 和表单测试。
- [ ] 完成 Slice Gate 并创建独立 Git checkpoint。

Explicit Boundary:

- 不实现完整 Application Shell 导航或业务 Feature 页面。
- 不把 `/auth/me` 或 `/auth/capabilities` 放入 Query Cache。

### Slice 3 - Shared UI Foundations and Application Shell

Status: NOT_STARTED

Goal: 建立服从蓝白产品视觉的最小 Shared UI、路由装配层、布局与 guards，为后续页面提供一致 Interface。

- [ ] 读取 SPEC 视觉规则、Architecture 第 3、11、12、13、14 节和 Application Shell spec。
- [ ] 建立全局 design tokens、CSS Modules 约定和 compact/standard/wide 共享断点。
- [ ] 在 `src/components/ui/` 实现当前 Slice 真正复用的 Button、Input/Form Control、Error/Empty State、Skeleton、Dialog/Drawer 等最小 primitives；不得预建空壳组件。
- [ ] 建立 Router、public/authenticated/capability guards 和 `src/pages/` 唯一路由装配层。
- [ ] 实现桌面 Sidebar、窄屏 Drawer、Top Bar、安全导航和 route-level error/loading 状态。
- [ ] Shell、Route Guard、Capability Guard 只读取 AuthProvider Snapshot。
- [ ] 实现安全 request ID 展示、键盘操作、焦点可见与 dialog focus return。
- [ ] 增加路由保护、capability discoverability、直接访问拒绝、responsive shell 和 accessibility 测试。
- [ ] 完成 Slice Gate；对浏览器可见流程执行适当 manual smoke；创建独立 Git checkpoint。

Explicit Boundary:

- 不实现会话、Chat、TaskPlan、文档或 Admin 的业务数据流。
- 不引入 Tailwind、完整 UI Library 或 E2E framework。

### Slice 4 - Conversations

Status: NOT_STARTED

Goal: 完成当前用户会话的创建、列表、选择、重命名、删除和消息历史读取，并建立稳定的私有 Query Key。

- [ ] 读取 Conversations spec，复核 Route/Schema/OpenAPI/runtime tests。
- [ ] 实现 conversation list/messages transport adapters 和 user-bound Query Keys。
- [ ] 实现 keyset pagination、稳定追加、ID 去重和服务端顺序保留。
- [ ] 实现新建、选择、重命名、确认删除和历史消息恢复。
- [ ] 从 list 派生当前会话摘要；禁止虚构 conversation detail endpoint/cache。
- [ ] 实现 pending 与 persisted 消息区分，为 Chat Slice 提供明确 seam。
- [ ] 实现 rename/delete/404/refreshing/error 的服务端收敛规则。
- [ ] 增加同 session 跨用户隔离、cursor、重命名顺序、删除、消息恢复和 cache invalidation 测试。
- [ ] 完成 Slice Gate 并创建独立 Git checkpoint。

### Slice 5 - RAG / Agent Chat Core

Status: NOT_STARTED

Goal: 使用唯一结构化 SSE 主线完成标准 RAG/Agent 对话、事件时间线、回答、来源与持久化收敛。

- [ ] 读取 Chat spec，并复核 `/rag/chat/stream/events` 的 Route/Schema/OpenAPI/public events/runtime tests。
- [ ] 实现 Chat request adapter；不得提交客户端推导的 ACL、内部 scoped ID 或未声明字段。
- [ ] 实现一个活动流/会话、前端 request ID 绑定、pre-stream replay 和 late-event isolation。
- [ ] 实现 Chat reducer：connecting/streaming/completed/failed/interrupted/cancelled。
- [ ] 实现 answer、sources、route、guard、clarification、TaskPlan reference 和 terminal event 展示。
- [ ] 对 unknown events 只保留 allowlisted safe projection，立即丢弃 raw payload。
- [ ] 实现净化 Markdown Viewer 和 knowledge/web source 安全导航；新增依赖前必须核对现有依赖并锁定精确版本。
- [ ] 实现 Web 两开关的基础请求映射和按用户/标签页存储；Dataset 细化留给 Slice 10。
- [ ] `done/error/interrupted/abort` 后统一 refetch conversation messages/list；stream body 开始后绝不自动 replay。
- [ ] 增加 chunking、terminal、abort、mismatch、unknown safety、source URL、Web toggle 和持久化收敛测试。
- [ ] 完成 Slice Gate；执行 Chat manual smoke；创建独立 Git checkpoint。

Explicit Boundary:

- React 问答网络记录只能出现 `POST /rag/chat/stream/events`。
- 不显示 Classic/LangGraph/provider 选择器。

### Slice 6 - TaskPlan

Status: NOT_STARTED

Goal: 完成 TaskPlan 列表、详情、Markdown、确认流、取消、重试和恢复。

- [ ] 读取 TaskPlan spec，复核 list wrapper、task-kind detail、控制接口、SSE 和 Idempotency contract。
- [ ] 实现 list/detail/markdown adapters、Query Keys、filters 和 keyset pagination。
- [ ] 按 task kind 保留完整 Domain Model，不压平成丢字段的通用模型。
- [ ] 实现结构化 status 驱动的 controls；禁止解析自然语言 message 决定按钮。
- [ ] Initial React 确认只使用 `/{id}/confirm/stream`。
- [ ] 确认流复用公共 SSE envelope/transport，业务 event 使用独立 TaskPlan union/reducer。
- [ ] 同一 deliberate action 保留 Idempotency-Key；`409` 和流终止后 refetch detail/list。
- [ ] 区分浏览器 abort 与服务端 cancel，禁止自动重放真实工具操作。
- [ ] 增加 list cursor、两种 task kind、幂等、409、confirm stream、abort/recovery、ownership 404 测试。
- [ ] 完成 Slice Gate；执行 TaskPlan manual smoke；创建独立 Git checkpoint。

### Slice 7 - Knowledge Documents

Status: NOT_STARTED

Goal: 完成公共/部门/grant 范围内的文档列表、详情、预览、来源跳转和受保护下载。

- [ ] 读取 Knowledge Documents spec，复核 Route/Schema/OpenAPI/CORS/runtime tests。
- [ ] 实现 list/detail/content/download adapters、Query Keys、filters 和 keyset pagination。
- [ ] 正确呈现 public 公共区域与非 public 部门语义，不在浏览器计算 ACL。
- [ ] 按 render mode 安全展示 Markdown/plain/extracted text，并显示 truncation/warnings。
- [ ] 实现 authenticated Blob download、`X-Source-Revision` 三方一致性校验和安全 `Content-Disposition` 文件名。
- [ ] revision 不一致时丢弃 Blob、refetch detail/content；object URL 使用后立即 revoke。
- [ ] 实现聊天 `doc_id` 来源站内跳转和隐藏式 404 体验。
- [ ] 增加 public/department/grant UI 状态、revision mismatch、Blob URL cleanup、header filename、404 和安全渲染测试。
- [ ] 完成 Slice Gate；执行 Documents manual smoke；创建独立 Git checkpoint。

### Slice 8 - User Access Management

Status: NOT_STARTED

Goal: 完成管理员和部门主管范围内的用户列表、详情、创建、完整 access 替换、状态修改和密码重置。

- [ ] 读取 User Access Management spec，复核 catalog/user Route/Schema/OpenAPI/runtime tests。
- [ ] 实现 server-trimmed catalog、用户 list/detail adapters、filters、cursor 和 Query Keys。
- [ ] 从 catalog 构建账号、部门、角色、权限选项；禁止硬编码或任意 code 输入。
- [ ] 实现创建与完整 access PUT snapshot、唯一主部门校验和 catalog drift 处理。
- [ ] 实现禁用、重置密码、账号类型变更的确认和 pending lock。
- [ ] 密码仅存在表单局部状态并在提交后清空；destructive mutations 不做乐观更新。
- [ ] 当前用户身份/能力受影响时调用 AuthProvider reload；其他用户只失效业务 Query。
- [ ] 增加 admin/manager/employee scope、422、403/404、409、自操作保护、credential revocation summary 测试。
- [ ] 完成 Slice Gate；执行 User Management manual smoke；创建独立 Git checkpoint。

### Slice 9 - Cross-Department Document Grants

Status: NOT_STARTED

Goal: 完成非 public 文档的精确跨部门只读授权、列表、审计展示和幂等撤销。

- [ ] 读取 Document Grants spec，复核 Route/Schema/OpenAPI/runtime tests。
- [ ] 实现 grant list/create/revoke adapters、filters、cursor 和 Query Keys。
- [ ] 创建流程只接受精确 target account 和 1–100 个非 public document IDs。
- [ ] 不建立未批准的跨部门用户目录，不为 public/同部门文档创建冗余 grant。
- [ ] 展示 created/existing counts、active/revoked audit facts 和安全错误。
- [ ] 创建/撤销不做乐观更新，并失效 grants 与相关 documents Query。
- [ ] 增加 manager/admin scope、精确文档、幂等重复、撤销收敛、public 排除和不可见资源测试。
- [ ] 完成 Slice Gate；执行 Document Grants manual smoke；创建独立 Git checkpoint。

### Slice 10 - NL2SQL and Web Search Refinements

Status: NOT_STARTED

Goal: 在统一 Chat 中补齐 Dataset 选择、NL2SQL 结构化结果与 Web Search 完整能力体验，不建立平行问答应用。

- [ ] 读取 NL2SQL、Web Search 和 Chat specs，复核 Dataset 和 public SSE event contracts。
- [ ] 仅在 capability 允许时加载 server-trimmed Dataset list。
- [ ] 强制 `dataset_id + nl2sql_action` 同时省略或同时提交；report 只在声明支持时可选。
- [ ] 实现 parameterized SQL、columns/rows、summary、truncated、warnings 和 text-only cells。
- [ ] 刷新只恢复服务端持久化的问题、摘要和终态，不自动重新提交以恢复完整表格。
- [ ] 完成 Web direct/fallback 两个独立控件、默认值、tab/user storage 和 capability false 映射。
- [ ] 只从后端 `href` 打开无凭据 HTTP(S) 外链；敏感 Dataset/内部文档/ACL 不进入 Web composition。
- [ ] 增加 capability、Dataset/action、report、stream-only result、refresh recovery、Web mapping、URL 和隐私测试。
- [ ] 验证网络记录无 `/nl2sql/query` 或其他未批准问答接口。
- [ ] 完成 Slice Gate；执行 NL2SQL/Web manual smoke；创建独立 Git checkpoint。

### Slice 11 - Final Integration and Release Readiness

Status: NOT_STARTED

Goal: 在不扩大 Scope 的前提下完成跨 Feature 集成、可访问性、响应式、错误恢复和最终交付证据。

- [ ] 全量复读 AGENTS、SPEC、Architecture、Development、Feature index 和全部 Feature specs。
- [ ] 核对所有 route、capability、Query Key、identity change 和 private-cache isolation。
- [ ] 核对 Chat/TaskPlan streaming 的 request ID、terminal、abort、interruption 和 refetch 语义。
- [ ] 核对 public/department/grant 文档访问、Admin scope、NL2SQL/Web 隐私与安全导航。
- [ ] 完成 compact/standard/wide 响应式、键盘、焦点、label、status announcement 和阻断错误体验。
- [ ] 运行全部 focused tests、`pnpm lint`、`pnpm typecheck`、`pnpm test`、`pnpm build`、`pnpm check` 和 `pnpm audit --audit-level high`。
- [ ] 按批准范围执行关键浏览器 manual smoke matrix；不得将其描述为自动 E2E。
- [ ] 检查完整 diff、generated contract drift、依赖变化、秘密和未批准 endpoint。
- [ ] 更新所有真实完成证据，创建最终 Git checkpoint。
- [ ] 满足 Completion 后将本计划移动到 `docs/exec-plans/completed/`。

## Slice Gate

任何 Slice 只有满足全部适用条件才能标记 `COMPLETED`：

- [ ] 当前 Slice 的实现与相关 SPEC/Architecture/Feature specs 一致。
- [ ] 后端 Route、Schema、OpenAPI 和 tested behavior 已核对，无未解决 Contract Gap。
- [ ] 当前 Slice 的 focused deterministic tests 通过。
- [ ] `pnpm check` 通过，并分别记录其中 lint、typecheck、全量 tests 和 production build 的实际结果。
- [ ] 若当前 Slice 修改了 `package.json`、`pnpm-lock.yaml` 或 dependency graph，必须运行 `pnpm audit --audit-level high`；若依赖未变化，可引用相同 lockfile 下最近一次成功的 audit evidence，无可引用证据时必须实际运行。网络原因导致无法验证时，明确记录命令、原因和未验证状态，不得伪称通过。
- [ ] 浏览器可见 Slice 已完成适当 manual smoke verification；纯 protocol Slice 可标记 not applicable 并说明理由。
- [ ] 完整 diff 已检查，无无关改动、重复 Interface、弱化断言或 speculative abstraction。
- [ ] 没有秘密、敏感 payload、凭证或私有服务数据进入代码、fixtures、snapshot、日志或输出。
- [ ] 本 Execution Plan 已及时更新 Current Slice、证据、Decision Log、Known Issues 和 Next Action。
- [ ] 已创建单一业务边界的 Git checkpoint，commit 内容不混入其他 Slice。
- [ ] checkpoint 后工作树状态符合本计划记录。

任一 Gate 失败时：

- 当前 Slice 保持 `IN_PROGRESS` 或标记 `BLOCKED`；
- 记录失败命令、错误、影响和唯一 Next Action；
- 不得进入下一 Slice；
- 不得删除失败测试、弱化断言、修改 Spec 迁就实现或把部分验证报告为完成。

## Execution Rules

每个 Slice 必须按以下顺序执行：

1. 读取 `AGENTS.md`、本计划和当前 Slice 相关 specs。
2. 检查 `git status --short --branch`、最近 commits、当前 diff、源码、测试、package 和 lockfile。
3. 按需重新核对真实后端 Route、Pydantic Schema、OpenAPI 和 tests；不得从旧文档猜网络契约。
4. 在本计划中确认唯一 Current Step、Next Action 和当前 working set。
5. 运行修改前 focused baseline；行为变化时优先先增加可失败的 deterministic test。
6. 只实现当前 Slice 的最小完整方案，保留 Architecture 定义的 module seam。
7. 开发期间先运行 focused tests，再运行更广验证。
8. 新增依赖前检查标准能力和现有依赖，核对 Node compatibility，锁定精确版本并更新 package、lockfile 与 Development 文档。
9. 完成后执行 Slice Gate，检查完整 diff 和未批准 endpoint/Scope。
10. 立即更新本计划，不把真实进度留在 conversation history 中。
11. 创建单一业务边界的 Git checkpoint；不得把多个 Feature 或无关后端改动混在一次 commit。
12. Gate 与 checkpoint 都完成后才能推进下一 Slice。

始终禁止：

- 提前实现未来 Slice 或为空的未来 Feature 建脚手架；
- 无关重构、批量格式化、宽泛依赖升级和 speculative abstraction；
- 复制 Auth Snapshot、token、ACL、SSE framing 或 Backend DTO 逻辑；
- 计算客户端 ACL、提交客户端推导权限范围或使用内部 scoped session ID；
- 使用未批准兼容/开发接口或增加 provider selector；
- 自动 replay 已开始的 Chat/TaskPlan POST stream；
- 原样展示、记录、缓存或持久化 unknown SSE payload；
- 为让实现通过而修改已批准产品 Scope 或 Feature Spec；
- 未经批准修改后端；
- 未实际运行就声称测试、build、audit、manual smoke 或 browser flow 通过。

## Context Recovery Protocol

当上下文被压缩、切换会话、任务恢复、Current Slice 不确定，或 conversation history 与仓库看起来不一致时，禁止立即继续编码。

必须依次执行：

1. 完整读取当前 `AGENTS.md`。
2. 完整读取本 Execution Plan，记录 Status、Current Slice、Current Step、Next Action 和 Blocking Issues。
3. 读取当前 Slice 相关的 SPEC、Architecture、Development 和 Feature specs。
4. 运行 `git status --short --branch`。
5. 运行 `git diff --stat`、读取当前完整 diff，并检查 staged diff。
6. 查看最近 Git commits，确认 checkpoint 和本计划记录是否一致。
7. 检查当前 Slice 已存在的源码、测试、package 和 lockfile；禁止仅看目录名推断完成度。
8. 运行最小相关测试；若状态仍不确定且没有记录中的 expected-red test，再运行 `pnpm check` 建立真实基线。
9. 将 Repository/Git/Tests 与本计划逐项比对；冲突时以仓库事实为准，并先修正本计划的状态、working set、known issue 和 next action。
10. 如发现 Backend Contract 不确定，读取 Route/Schema/OpenAPI/tested behavior；不能猜测。
11. 只确定一个可验证的 Next Action，再继续实现。

恢复完成后，必须在本计划记录恢复日期、确认的 HEAD、working tree 状态、验证命令和唯一 Next Action。Conversation history 不是进度 Source of Truth。

## Current Working Set

Current Slice:

- 2 - Authentication Lifecycle and AuthProvider

Completed in Current Slice:

- Slice 0 checkpoint 为 `768b6d8` 的前一 checkpoint `dfa5b7a`；`768b6d8` 记录用户批准、Context Recovery 证据和进入 Slice 1 的状态转换。
- 当前 backend OpenAPI snapshot 来自 monorepo HEAD `768b6d8`，最后影响 `src/fast_app` 的 commit 为 `25fad7a`；OpenAPI `3.1.0` 包含 58 paths、86 schemas。
- 后端 `scripts/tests/agent_research/test_rag_stream_contract.py` 通过，Chat 与 TaskPlan stream 的 `contract_version`、`request_id`、response header 和逻辑帧声明一致，无阻塞 Contract Gap。
- 精确锁定 `openapi-typescript` `7.13.0`；`pnpm install --frozen-lockfile`、生成命令和 generated drift check 通过。
- 已建立 generated HTTP transport type、DTO-to-Domain mapping rule、共享 HTTP/error seam、parameterized SSE media-type gate、SSE byte framer、Public Event validation、安全投影与 terminal semantics。
- deterministic tests 先以缺失 module 形成 expected-red，完成实现后 focused 16/16 通过；最终全量 Vitest 4 files / 17 tests 通过。
- 2026-08-25 最终 `pnpm check`：contract drift、lint、typecheck、17/17 tests、production build 全部通过。
- `pnpm audit --audit-level high`：No known vulnerabilities found。
- Slice 1 是纯 protocol Slice，browser manual smoke 不适用；没有修改现有环境检查 UI。
- 完整 diff、generated header、禁止 runtime endpoint 和敏感 OpenAPI default 已检查；唯一 sensitive-name default 是公开的 `TokenPairResponse.token_type`，不是凭证值。

Currently Working On:

- Slice 2 Authentication/Application Shell 文档复读和当前后端 Auth contract 核对。

Next Action:

- 读取 Authentication 与 Application Shell specs，并核对 Auth Route、Schema、OpenAPI 与 deterministic tests，建立 Slice 2 focused baseline。

Relevant Files:

- `AGENTS.md`
- `docs/exec-plans/active/frontend-initial-build.md`
- `docs/SPEC.md`
- `docs/ARCHITECTURE.md`
- `docs/features/authentication/feature.md`
- `docs/features/application-shell/feature.md`
- `src/api/http-client.ts`
- `src/app/AppProviders.tsx`
- `src/features/auth/`

Context Recovery Evidence (verified 2026-08-25):

- Confirmed HEAD before this plan transition: `dfa5b7a`。
- `git status --short --branch`: `master...origin/master`，无工作树修改。
- `git diff --stat`、完整 unstaged diff、`git diff --cached --stat` 与完整 staged diff：全部为空。
- 当前源码仍只有环境检查页、基础 Provider/MSW 与一个测试；没有 Slice 1 protocol 实现。
- Node `v24.14.0`、pnpm `10.32.1`；package/lockfile 未包含 `openapi-typescript`。
- `pnpm check`: lint、typecheck、1/1 Vitest、production build 全部通过。
- Blocking Issues: None。

## Decision Log

本章节只记录已经批准的产品/架构决定，以及不改变批准设计的 implementation-local decision。

- Decision Log 不得覆盖或隐式修改 `docs/SPEC.md`、Feature Specs 或 `docs/ARCHITECTURE.md`。
- 如果新的 implementation decision 会改变批准设计，必须停止相关实现并请求用户批准，不能先写入 Decision Log 使其成为既定事实。

### D001 - Progress Authority

Decision:

- Execution Plan 与当前 Git/Repository/Tests 共同作为实施进度事实；conversation history 不能单独裁决进度。

Reason:

- 防止上下文压缩、换会话或并行工作造成状态漂移。

Source:

- 用户批准的 execution-plan 要求；`AGENTS.md` active-plan rule。

### D002 - Contract Type Flow

Decision:

- 普通 HTTP 使用 FastAPI OpenAPI snapshot 生成 TypeScript transport types，再通过 Feature adapter 转为 Domain/UI Model；generated file 禁止手改。

Reason:

- 避免 Feature/Component 各自手写漂移的 Backend DTO。

Source:

- `docs/ARCHITECTURE.md` 第 2 节。

### D003 - Auth Snapshot Ownership

Decision:

- AuthProvider 独占 access token lifecycle、`CurrentUser`、`Capabilities`、refresh coordination 和 auth generation；`/auth/me`、`/auth/capabilities` 不进入 Query Cache。

Reason:

- 保证原子身份快照和 stale-response rejection，避免双重 Source of Truth。

Source:

- `docs/ARCHITECTURE.md` 第 4、5 节；Authentication spec。

### D004 - Streaming Transport

Decision:

- Chat 与 TaskPlan 复用 authorized fetch、SSE framing、public envelope、request ID 和安全 unknown projection；Feature 各自拥有业务 reducer。

Reason:

- 协议复杂性集中在深 module，同时保持业务状态语义独立。

Source:

- `docs/ARCHITECTURE.md` 第 2.2、6、7、8 节。

### D005 - Streaming Replay Rule

Decision:

- pre-stream eligible 401 最多 replay 一次；开始读取 stream 后任何断线都不自动 replay POST，先 refetch 服务端持久化状态。

Reason:

- 避免重复 turn、TaskPlan 确认和真实工具副作用。

Source:

- `docs/ARCHITECTURE.md` 第 6 节；Chat 与 TaskPlan specs。

### D006 - Page and UI Ownership

Decision:

- `src/pages/` 是唯一 route composition layer；Feature 不创建 pages。CSS Modules + global tokens + shared UI primitives 实现统一蓝白视觉，首期不引入完整 UI Library/Tailwind。

Reason:

- 避免 Page ownership、基础控件和视觉语言分裂。

Source:

- `docs/SPEC.md` 第 2 节；`docs/ARCHITECTURE.md` 第 3、12 节。

### D007 - Business-Sliced Delivery

Decision:

- 基础 protocol/auth/shell 之后，以 Conversations、Chat、TaskPlan、Documents、Users、Grants、NL2SQL/Web 分离 checkpoint；每个 Slice 通过 Gate 后才推进。

Reason:

- 保持 commit 可维护、测试证据清晰，避免多个业务模块混在同一次提交。

Source:

- `AGENTS.md` focused-change rules；本计划 Slice Gate。

### D008 - Browser Verification

Decision:

- 当前关键浏览器流程使用 manual smoke verification，不自行增加 Playwright/Cypress。

Reason:

- 当前已批准工具链只有 Vitest/jsdom/RTL/MSW，自动 E2E 需要新的架构与依赖批准。

Source:

- `docs/ARCHITECTURE.md` 第 14 节；`docs/DEVELOPMENT.md`。

## Known Issues

### KI001 - Business Implementation Has Not Started

Status: EXPECTED / NON-BLOCKING

Evidence:

- `src/app/App.tsx` 仍是环境检查页。
- MSW handlers 为空。
- 只有 `App.test.tsx` 一个环境测试。

Impact:

- 所有业务 Slice 均必须保持 `NOT_STARTED`，不能从示例或 conversation history 推断为 Slice 2。

Resolution:

- 审核并完成 Slice 0 后，从 Slice 1 开始。

### KI002 - OpenAPI Type Generator Is Not Installed

Status: RESOLVED IN SLICE 1

Evidence:

- `openapi-typescript` `7.13.0` 已精确写入 package/lockfile，snapshot、generated types、生成命令和 drift check 已提交到 Slice 1 working set。

Impact:

- 无；原 planned dependency gap 已关闭。

Resolution:

- 见 `docs/DEVELOPMENT.md` 第 2、4、8 节及 Slice 1 Gate Evidence。

### KI005 - openapi-typescript TypeScript 6 Peer Range

Status: VERIFIED UPSTREAM RISK / NON-BLOCKING

Evidence:

- Registry latest `openapi-typescript` `7.13.0` 的 manifest 仍声明 `typescript: ^5.x`；当前项目解析 TypeScript `6.0.3`。
- 当前 Node `24.14.0` 下 CLI generate、drift check、frozen install、TypeScript 6 typecheck、17 tests 和 production build 全部通过。

Impact:

- 当前实际工具链可用，但上游尚未正式扩大 peer range；未来生成器或 TypeScript 升级必须重新核对，不能把当前证据永久外推。

Resolution:

- 保持精确版本并显式记录风险，不添加 peer override 静默隐藏；升级时优先采用正式声明 TypeScript 6 支持的版本。

### KI003 - Markdown Implementation Dependency Is Undecided

Status: PLANNED / NON-BLOCKING

Evidence:

- 当前依赖没有 Markdown renderer/sanitizer，而 Chat、TaskPlan 和 Documents 要求安全 Markdown Viewer。

Impact:

- 在首次实现 Shared Markdown Viewer 前需要核对现有能力并选择最小、兼容、可安全配置的精确依赖或实现方案。

Resolution:

- 在 Slice 3/5 的局部计划中形成依赖决定并更新 package/lockfile/Development；不得渲染 raw HTML。

### KI004 - No Automated E2E Framework

Status: APPROVED CONSTRAINT / NON-BLOCKING

Evidence:

- 当前工具链为 Vitest、jsdom、React Testing Library 和 MSW，没有 Playwright/Cypress。

Impact:

- 关键浏览器流程需要人工 smoke evidence，不能声称自动 E2E coverage。

Resolution:

- 按每个浏览器可见 Slice 与最终 Slice 的 manual smoke gate 执行；未经批准不增加 E2E 依赖。

### Contract Gaps

- 当前没有已知的阻塞性 Backend Contract Gap；Slice 1 已核对 Route/Schema/OpenAPI/SSE contract test。
- 每个业务 Slice 仍须复核对应真实 Route/Schema/tests；如发现 drift，必须新增带 Evidence/Impact/Recommendation 的 gap 并停止受影响实现。

## Completion

只有 Slice 0–11 全部通过各自 Slice Gate，Initial React frontend 才能标记完成。

最终完成步骤：

1. 将全局 Status 改为 `COMPLETED`，Current Slice/Step/Next Action 更新为完成状态。
2. 记录最终 frontend commit、backend contract snapshot commit、依赖版本和生成命令。
3. 运行并记录最终 `pnpm lint`、`pnpm typecheck`、`pnpm test`、`pnpm build`、`pnpm check`、`pnpm audit --audit-level high`。
4. 完成并记录关键浏览器 manual smoke matrix；明确它不是自动 E2E。
5. 复核所有批准 endpoint、auth/ACL、SSE、TaskPlan、document revision、NL2SQL/Web privacy 和跨用户 cache isolation。
6. 检查完整 Git diff/log/status，确认无无关改动、秘密、generated drift 或未批准 Scope。
7. 创建最终单一业务边界 checkpoint。
8. 将本文件从 `docs/exec-plans/active/frontend-initial-build.md` 移动到 `docs/exec-plans/completed/frontend-initial-build.md`，并在同一 checkpoint 更新 AGENTS 导航所需状态。

完成前不得删除 active plan、伪造 checkbox、跳过失败 Gate 或仅凭 conversation history 宣称交付。

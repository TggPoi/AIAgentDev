# Initial React Frontend Execution Plan

## Status

Status: ACTIVE

Plan Approval: APPROVED BY USER ON 2026-08-25

Current Slice: 6 - TaskPlan

Current Step: Slice 6 只读页面已由 frontend checkpoint `ab8f2d9` 完成并验证；真实 `/tasks` routes 已接入 filters/list/detail/Markdown 与两种 task kind 展示，现进入 status-driven control policy、cancel/retry 与 confirm-stream reducer

Next Action: 为结构化 status/task kind control policy、cancel/retry mutation、confirm-stream request ID/Idempotency-Key、TaskPlan public event reducer、409/abort/interrupted refetch 新增 focused expected-red tests，再实现最小 control/stream seam

Blocking Issues: None

Last Updated: 2026-08-29 (Asia/Shanghai)

## Goal

按照已经批准的产品、架构和 Feature 规范，全量实现 Initial React frontend，并以可验证、可恢复、按业务边界提交的 Slice 推进。

本计划管理 Initial React frontend 的完整实施过程、当前状态、验证证据和上下文恢复，不修改产品 Scope。实施期间严格按照 Slice、Slice Gate 和 Blocking Condition 推进。

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

Status: COMPLETED

Goal: 完成认证 Bootstrap Snapshot、token 生命周期、共享 refresh coordination 和认证页面，使后续 Feature 只依赖一个稳定 AuthProvider Interface。

- [x] 读取 Authentication 与 Application Shell specs，并复核后端 Auth Route/Schema/OpenAPI/测试。
- [x] 实现 access token memory storage 与 refresh token tab-scoped `sessionStorage` lifecycle。
- [x] 实现 single-flight refresh；eligible 请求最多 replay 一次，login/refresh/logout/already-replayed 不递归刷新。
- [x] 将共享 authorized fetch 与 AuthProvider token/refresh Interface 对接，不复制 token 或 refresh 状态。
- [x] 实现 `CurrentUser + Capabilities` 原子 Bootstrap Snapshot，二者不进入 TanStack Query。
- [x] 实现 `authGeneration`/epoch stale-response rejection，包括并发 reload、logout、identity change、refresh failure 和 lifecycle reset。
- [x] 实现 identity change 时 abort 活动流并清空全部私有 Query Cache。
- [x] 实现登录、启动恢复、注销、修改密码和安全 return-path 校验。
- [x] 实现认证相关 loading/error/field validation，禁止密码和 token 泄漏。
- [x] 增加并发 401、reload A/B 乱序、logout 后旧 reload、refresh failure、cache clear、return path 和表单测试。
- [x] 完成 Slice Gate 并创建独立 Git checkpoint。

Exit Evidence:

- 独立 frontend checkpoint：`265e900`。
- `pnpm check` 通过 generated drift、lint、typecheck、10 files / 47 tests 与 production build。
- 浏览器人工 smoke 验证登录页桌面与 360px 窄屏布局、无横向溢出、表单语义、焦点样式和 console 无 warning/error；验证标签页与 dev server 已清理。
- staged diff check、禁止 React endpoint 搜索与最终工作树检查通过；未修改 package/lockfile，沿用 Slice 1 同 lockfile 的 successful audit evidence。

Explicit Boundary:

- 不实现完整 Application Shell 导航或业务 Feature 页面。
- 不把 `/auth/me` 或 `/auth/capabilities` 放入 Query Cache。

### Slice 3 - Shared UI Foundations and Application Shell

Status: COMPLETED

Goal: 建立服从蓝白产品视觉的最小 Shared UI、路由装配层、布局与 guards，为后续页面提供一致 Interface。

- [x] 读取 SPEC 视觉规则、Architecture 第 3、11、12、13、14 节和 Application Shell spec。
- [x] 建立全局 design tokens、CSS Modules 约定和 compact/standard/wide 共享断点。
- [x] 在 `src/components/ui/` 实现当前 Slice 真正复用的 Button、Input/Form Control、Error/Empty State、Skeleton、Dialog/Drawer 等最小 primitives；不得预建空壳组件。
- [x] 建立 Router、public/authenticated/capability guards 和 `src/pages/` 唯一路由装配层。
- [x] 实现桌面 Sidebar、窄屏 Drawer、Top Bar、安全导航和 route-level error/loading 状态。
- [x] Shell、Route Guard、Capability Guard 只读取 AuthProvider Snapshot。
- [x] 实现安全 request ID 展示、键盘操作、焦点可见与 dialog focus return。
- [x] 增加路由保护、capability discoverability、直接访问拒绝、responsive shell 和 accessibility 测试。
- [x] 完成 Slice Gate；对浏览器可见流程执行适当 manual smoke；创建独立 Git checkpoint。

Exit Evidence:

- 独立 frontend checkpoint：`c324170`。
- `pnpm check` 通过 generated drift、lint、typecheck、12 files / 54 tests 与 production build。
- tests 覆盖 capability 导航/直接访问/动态失权、安全回退、抽屉键盘关闭与焦点回收、通用页面状态、render error boundary 和共享表单控件。
- authenticated manual smoke 使用本机临时假 Auth 服务验证桌面与 360px shell、用户菜单、能力入口、抽屉自动收起、焦点循环、Escape/焦点回收、无横向溢出和无 console warning/error；临时服务、dev server 与标签页均已清理。

Explicit Boundary:

- 不实现会话、Chat、TaskPlan、文档或 Admin 的业务数据流。
- 不引入 Tailwind、完整 UI Library 或 E2E framework。

### Slice 4 - Conversations

Status: COMPLETED

Goal: 完成当前用户会话的创建、列表、选择、重命名、删除和消息历史读取，并建立稳定的私有 Query Key。

- [x] 读取 Conversations spec，复核 Route/Schema/OpenAPI/runtime tests。
- [x] 实现 conversation list/messages transport adapters 和 user-bound Query Keys。
- [x] 实现 keyset pagination、稳定追加、ID 去重和服务端顺序保留。
- [x] 实现新建、选择、重命名、确认删除和历史消息恢复。
- [x] 从 list 派生当前会话摘要；禁止虚构 conversation detail endpoint/cache。
- [x] 实现 pending 与 persisted 消息区分，为 Chat Slice 提供明确 seam。
- [x] 实现 rename/delete/404/refreshing/error 的服务端收敛规则。
- [x] 增加同 session 跨用户隔离、cursor、重命名顺序、删除、消息恢复和 cache invalidation 测试。
- [x] 完成 Slice Gate 并创建独立 Git checkpoint。

Exit Evidence:

- focused Conversations/Dialog tests 为 3 files / 12 tests 全部通过；包含先失败后通过的 data seam、真实 App/MSW 页面流、Dialog focus return 与安全 form-level mutation error。
- `pnpm check` 通过 generated contract drift、lint、typecheck、15 files / 66 tests 与 production build；package、lockfile 和 dependency graph 未变化，沿用 Slice 1 相同 lockfile 下 `pnpm audit --audit-level high` 的成功证据。
- manual browser smoke 使用仅含虚构数据的本机临时 Auth/Conversation 服务：验证 1280px 历史消息/来源/TaskPlan 恢复、新建后按服务端 session ID 导航、重命名、删除确认、Dialog Escape 与焦点回收、直接 404 安全状态；360px 验证单列布局、Dialog 完整位于 viewport 内且 body/main 无横向溢出；console warning/error 均为空。
- 浏览器 smoke 未实际提交最终删除，只验证不可恢复警告与确认边界；实际 DELETE、204 解析、cache 清理、导航和列表收敛由真实 App/MSW deterministic test 提交并通过。临时 fake service、Vite dev server 与 browser tab 均已清理。
- 当前 Slice 未修改 package/lockfile/generated contract；只使用批准的 Conversation routes，未引入 conversation detail endpoint、未来 Feature、global state/UI/E2E dependency 或客户端 ACL。
- 独立 frontend checkpoint：`5821b25`；checkpoint 后工作树干净，branch 为 `master...origin/master [ahead 14]`。

### Slice 5 - RAG / Agent Chat Core

Status: COMPLETED

Goal: 使用唯一结构化 SSE 主线完成标准 RAG/Agent 对话、事件时间线、回答、来源与持久化收敛。

- [x] 读取 Chat spec，并复核 `/rag/chat/stream/events` 的 Route/Schema/OpenAPI/public events/runtime tests。
- [x] 实现 Chat request adapter；不得提交客户端推导的 ACL、内部 scoped ID 或未声明字段。
- [x] 实现一个活动流/会话、前端 request ID 绑定、pre-stream replay 和 late-event isolation。
- [x] 实现 Chat reducer：connecting/streaming/completed/failed/interrupted/cancelled。
- [x] 实现 answer、sources、route、guard、clarification、TaskPlan reference 和 terminal event 展示。
- [x] 对 unknown events 只保留 allowlisted safe projection，立即丢弃 raw payload。
- [x] 实现净化 Markdown Viewer 和 knowledge/web source 安全导航；新增依赖前必须核对现有依赖并锁定精确版本。
- [x] 实现 Web 两开关的基础请求映射和按用户/标签页存储；Dataset 细化留给 Slice 10。
- [x] `done/error/interrupted/abort` 后统一 refetch conversation messages/list；stream body 开始后绝不自动 replay。
- [x] 增加 chunking、terminal、abort、mismatch、unknown safety、source URL、Web toggle 和持久化收敛测试。
- [x] 完成 Slice Gate；执行 Chat manual smoke；创建独立 Git checkpoint。

Exit Evidence:

- frontend checkpoint `633a07a` 在既有 non-Markdown core checkpoint `1444099` 之上完成共享安全 Markdown Viewer、实时/历史回答与 source preview 集成、精确 dependency/lockfile mutation 和对应 tests；active plan 状态转换由后续 plan checkpoint 记录。
- focused Markdown/Conversations tests 为 2 files / 12 tests 通过；最终 `pnpm check` 通过 generated drift、lint、typecheck、19 files / 82 tests 与 production build。
- dependency graph 变化后 `pnpm audit --audit-level high` 返回 `No known vulnerabilities found`。
- desktop/360px Chat manual smoke 覆盖历史、实时和持久化 Markdown、安全/不安全来源、unknown payload 丢弃、TaskPlan link、Web 设置刷新恢复、无横向溢出和空 console；临时服务、脚本、dev server 与 browser tab 均已清理。
- final diff/staged boundary、generated contract 无差异、生产代码唯一 RAG route 和敏感 marker 检查通过；checkpoint 不包含 active plan 状态转换或 backend/未来 Slice 改动。

Explicit Boundary:

- React 问答网络记录只能出现 `POST /rag/chat/stream/events`。
- 不显示 Classic/LangGraph/provider 选择器。

### Slice 6 - TaskPlan

Status: IN_PROGRESS

Goal: 完成 TaskPlan 列表、详情、Markdown、确认流、取消、重试和恢复。

- [x] 读取 TaskPlan spec，复核 list wrapper、task-kind detail、控制接口、SSE 和 Idempotency contract。
- [x] 实现 list/detail/markdown adapters、Query Keys、filters 和 keyset pagination。
- [x] 按 task kind 保留完整 Domain Model，不压平成丢字段的通用模型。
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

- 6 - TaskPlan

Completed in Current Slice:

- Slice 0 checkpoint 为 `768b6d8` 的前一 checkpoint `dfa5b7a`；`768b6d8` 记录用户批准、Context Recovery 证据和进入 Slice 1 的状态转换。
- Slice 1 最初导出的 backend OpenAPI snapshot 来自 monorepo HEAD `768b6d8`，最后影响当时 `src/fast_app` 的 commit 为 `25fad7a`；该历史 snapshot 为 OpenAPI `3.1.0` / 58 paths / 86 schemas，随后已由 backend `313d634` 对应的 58 paths / 88 schemas snapshot supersede。
- 后端 `scripts/tests/agent_research/test_rag_stream_contract.py` 通过，Chat 与 TaskPlan stream 的 `contract_version`、`request_id`、response header 和逻辑帧声明一致，无阻塞 Contract Gap。
- 精确锁定 `openapi-typescript` `7.13.0`；`pnpm install --frozen-lockfile`、生成命令和 generated drift check 通过。
- 已建立 generated HTTP transport type、DTO-to-Domain mapping rule、共享 HTTP/error seam、parameterized SSE media-type gate、SSE byte framer、Public Event validation、安全投影与 terminal semantics。
- deterministic tests 先以缺失 module 形成 expected-red，完成实现后 focused 16/16 通过；最终全量 Vitest 4 files / 17 tests 通过。
- 2026-08-25 最终 `pnpm check`：contract drift、lint、typecheck、17/17 tests、production build 全部通过。
- `pnpm audit --audit-level high`：No known vulnerabilities found。
- Slice 1 是纯 protocol Slice，browser manual smoke 不适用；没有修改现有环境检查 UI。
- 完整 diff、generated header、禁止 runtime endpoint 和敏感 OpenAPI default 已检查；唯一 sensitive-name default 是公开的 `TokenPairResponse.token_type`，不是凭证值。
- Slice 2 已完整读取 Authentication/Application Shell specs，并核对 `auth_routes.py`、`auth_schema.py`、OpenAPI 与当前 TestClient runtime。
- 后端 `test_auth_identity_capabilities.py` 和 `test_auth_session_security.py::assert_http_contract` 均通过；frontend `src/api/http-client.test.ts` baseline 7/7 通过。
- 复核发现 CG001：认证 `422` 的 OpenAPI schema 与实际全局异常 handler 响应冲突，且 runtime 缺少 Feature spec 所需的字段位置。
- CG001 backend contract 已在独立 checkpoint `313d634` 修复：只为三个受影响 Auth route 投影 allowlisted 字段，未知/不安全错误保留 form-level，其他 backend API 的 validation runtime shape 保持不变。
- backend Auth validation expected-red/green、identity/capabilities、session HTTP、schema descriptions 与 RAG/TaskPlan stream contract tests 通过；runtime 与 OpenAPI 均验证一致。
- frontend OpenAPI snapshot 已从 backend `313d634` 重新导出为 OpenAPI `3.1.0` / 58 paths / 88 schemas，generated transport types 已重新生成；`pnpm contracts:check` 与 `pnpm typecheck` 通过。
- 本次 contract sync 的 `pnpm check` 通过：generated drift、lint、typecheck、4 files / 17 tests、production build 全部成功；lockfile 未变化，沿用 Slice 1 同 lockfile 的 successful audit evidence，纯 contract artifact 无新增 browser manual smoke。
- Slice 2 已在 checkpoint `265e900` 完成：AuthProvider 独占 access/refresh token、single-flight replay、原子身份/能力快照、epoch stale-response rejection、私有 cache/activity 清理、登录/注销/修改密码与安全 return path。
- Slice 2 的 `pnpm check` 为 10 files / 47 tests 全部通过，production build 成功；browser manual smoke 覆盖桌面与 360px 登录页、无横向溢出、表单语义、焦点样式和无 console warning/error。
- Slice 3 已在 checkpoint `c324170` 完成 shared design tokens、Button/TextField/Drawer/PageState primitives、三层路由、capability guard、响应式 Shell、Top Bar、用户菜单和安全 render/error 状态。
- Slice 3 的 `pnpm check` 为 12 files / 54 tests 全部通过，production build 成功；authenticated desktop/360px manual smoke、抽屉焦点循环/Escape/焦点回收和 console 检查通过。
- 用户于 2026-08-26 授权严格受限的 CG002 fix；backend test 先因 Conversation runtime 缺少 `field_errors` expected-red，再由独立 checkpoint `2a13eb3` 完成两个 Route 的 `title` allowlist projection、422 OpenAPI 声明和 runtime/OpenAPI/no-sensitive-echo/regression tests。
- backend Conversation/Auth validation contract、Conversation HTTP、Auth identity/session HTTP 和 schema field-description regressions 通过；非 allowlisted Route 仍保持原 validation response shape，path `session_id` validation 仍为 `field_errors=[]`。
- frontend OpenAPI snapshot 已从 backend `2a13eb3` 重新导出，仍为 OpenAPI `3.1.0` / 58 paths / 88 schemas；Conversation POST/PATCH 422 均引用 `RequestValidationErrorResponse`，field enum 只新增 `title`。generated types 已重新生成，`pnpm contracts:check`、typecheck 与完整 `pnpm check`（12 files / 54 tests + production build）通过。
- Conversations data/UI 的 expected-red tests 已分别证明缺失 module、缺失 route implementation、Dialog focus return 和 form-level mutation error；最小实现完成后 focused 3 files / 12 tests 与 typecheck 通过。
- 已建立 generated transport alias、DTO-to-domain adapter、opaque cursor、稳定 page merge、user-bound Query Keys 和 create/rename/delete invalidation；页面只从 list 派生当前摘要，没有调用或缓存不存在的 conversation detail endpoint。
- `ConversationsWorkspace` 已使用真实 App/AuthProvider/QueryClient/MSW seam 覆盖选择、分页、消息/来源/TaskPlan 恢复、创建导航、422 `title` 映射、form-level 安全错误、重命名服务端重排、404 安全状态、删除确认与 cache 收敛。
- 按用户授权完成后续 mutation 422 只读 inventory：当前 snapshot 中实际会被 Slice 5/6/8/9 使用的 mutation endpoints 仍声明 `HTTPValidationError`；代表性 `/admin/users` 与 `/admin/document-access/grants` runtime validation 返回公共 form-level shape。该风险已记录为 KI006，不预修复、不阻塞 Slice 4。
- Slice 4 已在独立 frontend checkpoint `5821b25` 完成 Conversations transport/domain/query/page flow、历史消息/来源/TaskPlan/终态恢复、create/rename/delete/404 收敛和可访问 Dialog。
- Slice 4 最终 `pnpm check` 通过 generated drift、lint、typecheck、15 files / 66 tests 与 production build；1280px/360px manual browser smoke 通过，临时服务与 browser tab 已清理，checkpoint 后工作树干净。
- Slice 5 已完整重读 Chat spec 与相关 SPEC/Architecture，检查现有 `HttpClient.openEventStream()`、SSE parser/public event contract、Conversation query/reconciliation seams 和 package/lockfile；进入 reconnaissance 时工作树干净。
- backend `test_rag_stream_contract.py` 通过，确认 structured Chat event order、public envelope、request ID header、SSE OpenAPI 200 response 和安全 source navigation baseline。
- KI006 的 Chat 风险已用当前 `RagChatRequest`、全局 validation handler 和实际 Route OpenAPI 复核为 CG003：空白 `query` 加未批准 marker 返回 `422`，runtime keys 只有 `code/error_category/message/request_id/trace_id`，marker 未回显；OpenAPI 422 仍引用 `HTTPValidationError`。
- CG003 已由独立 backend checkpoint `d3d95ba` 修复：只为 `POST /rag/chat/stream/events` 投影公开顶层 `query`，显式声明安全 422 model，并增加 runtime/OpenAPI/no-sensitive-echo/form-level fallback/legacy-route regression test；Auth、Conversation、RAG stream、Conversation HTTP、Auth identity/session 和 schema description regressions 全部通过。
- frontend OpenAPI snapshot 已从 `d3d95ba` 重新导出，仍为 OpenAPI `3.1.0` / 58 paths / 88 schemas；只有安全字段 enum 新增 `query` 且 structured Chat 422 改为 `RequestValidationErrorResponse`，legacy Chat 422 保持 `HTTPValidationError`。generated types、contract drift、lint、typecheck、15 files / 66 tests 与 production build 全部通过。
- Slice 5 frontend expected-red/green 已建立 generated `RagChatRequest` adapter、安全 `query` 422 映射、唯一 structured Chat API、request-ID 绑定、feature reducer 与 Chat/Conversation page composition；无其他 RAG endpoint 调用。
- deterministic tests 覆盖 capability-off/on Web 字段、按用户/标签页偏好恢复、增量回答与持久化 refetch、pre-stream 422、terminal-free EOF、abort/duplicate-send、late event、error terminal、mismatch protocol、unknown raw-payload 丢弃、澄清、TaskPlan、stale 和 knowledge/credential-free Web source navigation。
- Auth private-activity abort 生命周期同时清除当前用户 Web 偏好；session/user key 变化卸载并 abort 旧 ChatWorkspace，防止旧流进入新会话。历史与实时来源复用同一 credential-free HTTP(S) URL 过滤。
- 2026-08-27 中间 `pnpm check` 通过 contract drift、lint、typecheck、18 files / 81 tests 与 production build；package/lockfile/generated contract 均无本轮意外差异。
- 官方 metadata 确认 `react-markdown@10.1.0` 与 `remark-gfm@4.0.1` 兼容当前 React 19/Node 24/ESM；计划使用 `skipHtml`、自定义 URL/filter/component 且不安装 `rehype-raw`。实际安装被环境安全审查拒绝，package/lockfile 未变化，Slice 5 因此保持 BLOCKED。
- verified non-Markdown implementation 与 blocker 状态已由恢复 checkpoint `1444099` 持久化；该 commit 明确不代表 Slice Gate 完成。
- 用户于 2026-08-27 明确批准安装 `react-markdown@10.1.0` 与 `remark-gfm@4.0.1`；dependency blocker 已解除，Slice 5 恢复为 IN_PROGRESS。
- `react-markdown@10.1.0` 与 `remark-gfm@4.0.1` 已精确写入 package/lockfile；共享 `MarkdownViewer` 已实现 GFM、raw HTML 禁用、图片丢弃与 credential-free HTTP(S) link policy，并接入实时回答、持久化 assistant message 和 source preview。
- 恢复时 focused Markdown/Conversations tests 为 2 files / 12 tests 通过，contract drift、typecheck、全量 19 files / 82 tests 与 production build 分别通过；完整 `pnpm check` 只在 `MarkdownViewer` render 内定义 link renderer 的 lint warning 处停止。
- link renderer 已移到 module scope；修复后 focused 2 files / 12 tests、lint 和 typecheck 通过，完整 `pnpm check` 通过 contract drift、lint、typecheck、19 files / 82 tests 与 production build。
- dependency graph 变化后的 `pnpm audit --audit-level high` 返回 `No known vulnerabilities found`。
- Chat manual browser smoke 使用仅监听本机的虚构 Auth/Conversation/structured SSE service：desktop 与 360px 均验证历史、实时和持久化 Markdown；raw HTML/unknown secret 不进入页面，credential URL 不生成链接，安全外链带 `_blank` 与 `noopener noreferrer`，实时 source preview 使用 Markdown，TaskPlan link 正确，Web 设置刷新恢复，360px 无横向溢出且 console warning/error 为空。临时 browser tab、service、dev server 和 smoke script 已清理。
- Slice 5 Markdown completion 已由独立 frontend checkpoint `633a07a` 持久化；完整 Slice 5 由 non-Markdown core `1444099`、Markdown completion `633a07a` 及本计划记录的 Gate evidence 共同证明。

Currently Working On:

- Slice 6 / IN_PROGRESS。CG004-CG007 已全部关闭；checkpoint `758929d` 完成 data seam，checkpoint `ab8f2d9` 完成真实 `/tasks` list/detail/Markdown 只读页面与两类详情展示，现进入结构化 controls/confirm-stream。

Next Action:

- 为结构化 status/task kind control policy、cancel/retry mutation、confirm-stream request ID/Idempotency-Key、TaskPlan public event reducer、409/abort/interrupted refetch 新增 focused expected-red tests，再实现最小 control/stream seam。

Slice 6 Read-only Page Evidence (verified 2026-08-29):

- 真实 App/AuthProvider/QueryClient/MSW expected-red 先证明 `/tasks` 仍是 placeholder；frontend checkpoint `ab8f2d9` 随后用 `TaskPlanPage` 与 `TaskPlanWorkspace` 接入真实 routes，pages 只负责 feature composition。
- list 页面从 URL 读取 `status/session_id`，保留 backend order、支持 keyset load-more 并展示 task kind/status；detail 页面按 research/document variant 展示独有结构，计划 Markdown 复用共享安全 `MarkdownViewer`，raw HTML 不执行。
- focused App/MSW tests 2/2 通过，覆盖 filters 传输、列表顺序、research detail、结构化状态和安全 Markdown；首次 green 尝试由测试捕获错误的 Markdown prop 接线，修正后 typecheck/lint 通过。
- 完整 `pnpm check` 通过 contract drift、lint、typecheck、21 files / 88 tests 与 production build。该 checkpoint 尚不宣称 controls、confirm stream、404/refreshing/error 完整 acceptance 或 manual browser smoke 已完成。

Slice 6 Data Seam Evidence (verified 2026-08-29):

- focused expected-red 先因 `task-plan-api` 等 module 不存在失败；frontend checkpoint `758929d` 随后建立 generated DTO aliases、list/detail/Markdown adapters、research/document 判别 Domain Model、opaque cursor merge、user-bound keys 与 TanStack Query hooks。
- focused `task-plan-data.test.ts` 4/4 通过，覆盖跨用户 key isolation、服务端顺序/ID 去重、两种 task kind 判别与完整顶层字段、list filter/cursor URL 编码、detail 和参数化 `text/plain` Markdown response。
- `pnpm typecheck`、`pnpm lint` 与完整 `pnpm check` 通过：contract drift、lint、typecheck、20 files / 86 tests、production build 全部成功；package/lockfile/generated contract 未在该 checkpoint 变化，browser smoke 对纯 data seam 不适用。

CG006 Closure Evidence (verified 2026-08-29):

- backend checkpoint `2ca4bcc` 为 confirm-stream 建立严格公共 Pydantic event models/discriminated union 和逐字段 projection；unknown/internal events 被丢弃，raw step output、sub-question answer、tool calls/arguments、ACL/Scope、Dataset rows、internal URL 与 payload 自带 request ID 不进入公开事件。
- Route 只在写 SSE 前经过公共 projection；OpenAPI 200 使用 FastAPI 注册的 `#/components/schemas/TaskPlanPublicEventFrame`，避免局部 `$defs` 无法生成 transport types。executor、状态机、真实工具执行、非流式 confirm 与 legacy Chat stream 未修改。
- CG006 public contract、RAG stream、schema descriptions、CG004 detail、CG005 validation、CG007 visibility、Research v2、TaskPlan list HTTP 及 shared Auth/Conversation/Chat regressions通过。完整 TaskPlan list database test 因本机 PostgreSQL 未运行而连接被拒绝；同文件不依赖数据库的 `assert_http_contract()` 单独通过，该环境限制与 CG006 修改无关。
- frontend snapshot/type sync checkpoint `d30d7ea` 从 backend `2ca4bcc` 导出 OpenAPI `3.1.0` / 58 paths / 136 schemas；逐路径比较只有 confirm-stream 200 改变。`pnpm contracts:generate`、`pnpm contracts:check`、typecheck 与完整 `pnpm check` 通过（19 files / 82 tests + production build）。CG006 Runtime = OpenAPI = generated types = Tests，关闭该 gap。

Context Recovery Evidence (verified 2026-08-29 after quota interruption):

- frontend/backend 再次确认共享 Git root，branch 为 `master...origin/master [ahead 36]`，HEAD 为 `5aa31358f32e7c5654a341a78e591d1c5c4a7bc7`；staged diff 为空。
- frontend tracked working tree 与 package/lockfile/generated contract 均无 CG006 修改；committed OpenAPI confirm-stream 仍是 generic `RagSseEventFrame`，generated types 尚无 TaskPlan public event union，证明 frontend contract sync 尚未发生。
- backend tracked working set 只有 CG006 Route 与既有 RAG stream contract test；另有 CG006 新 public event schema/test 两个未跟踪文件。外部 evaluation builder/report/test/fixture 未跟踪文件仍不属于 Initial React working set，本 Slice 不读取、不修改、不暂存。
- CG006 expected-red 曾在旧 `_format_sse_event()` 原样保留 step output 时失败；当前 `test_agent_task_plan_stream_public_contract.py` 与更新后的 `test_rag_stream_contract.py` 已实际通过，确认代表性 research/document/step/error/done 安全投影、unknown event 丢弃与 OpenAPI discriminator union。
- CG004 detail、CG005 validation、CG007 resource visibility 与 Research v2 focused regressions在中断前同一批命令中通过；`test_schema_field_descriptions.py` 于本次恢复再次通过，但真实测试源码尚未收录新 `agent_task_plan_stream_schema.py`，因此不能作为 CG006 schema-description 完成证据。
- Repository/Git/Tests 表明计划原 Next Action“新增 expected-red test”已过期；已先修正为唯一 Next Action：补齐并纳入 public schema field descriptions，再完成 focused regressions、独立 backend checkpoint、frontend OpenAPI/types sync 与 plan closure。

Relevant Files:

- `AGENTS.md`
- `docs/exec-plans/active/frontend-initial-build.md`
- `docs/SPEC.md`
- `docs/ARCHITECTURE.md`
- `docs/features/rag-agent-chat/feature.md`
- `contracts/backend-openapi.json`
- `src/api/generated/backend-schema.ts`
- `src/api/sse/`
- `src/api/http-client.ts`
- `src/app/App.tsx`
- `src/pages/ChatPage.tsx`
- `src/features/conversations/`
- `../python-agent-study/src/fast_app/api/rag_chat_routes.py`
- `../python-agent-study/src/fast_app/schemas/rag_chat_schema.py`
- `../python-agent-study/scripts/tests/agent_research/test_rag_stream_contract.py`
- `../python-agent-study/scripts/tests/document_security/test_rag_chat_validation_contract.py`
- `docs/features/task-plans/feature.md`
- `src/api/sse/public-events.ts`
- `../python-agent-study/src/fast_app/api/agent_task_plan_routes.py`
- `../python-agent-study/src/fast_app/schemas/agent_task_plan_schema.py`
- `../python-agent-study/src/fast_app/domain/agent_task_plan.py`
- `../python-agent-study/src/fast_app/domain/research_task_plan.py`
- `../python-agent-study/scripts/tests/agent_research/test_agent_task_plan_list.py`

Context Recovery Evidence (verified 2026-08-28 after CG004-CG006 authorization):

- frontend/backend 目录再次确认共享 Git root `D:/AI_Agent_Project` 与 HEAD `bf384c5cf3dd8e884e2354299c30ed7fcee237e9`，branch 为 `master...origin/master [ahead 24]`；frontend scoped unstaged/staged diff 为空，backend tracked unstaged/staged diff 为空。
- backend 当前另有 7 个未跟踪 evaluation dataset builder/test/report/fixture 文件，均不属于 Initial React Slice 6 working set；本 Slice 不读取、不修改、不暂存，也不把它们计入 contract fix checkpoint。
- 最近 checkpoints `633a07a`、`215761c` 与 `bf384c5` 分别证明 Slice 5 Markdown implementation、Slice 5 Gate/进入 TaskPlan，以及 CG004-CG006 blocker 记录；最后 verified completed Slice 仍为 5，Slice 0-5 不重新实现。
- frontend `src/features/task-plans/` 仍不存在，`/tasks` 仅装配 placeholder；package/lockfile 精确保留 `openapi-typescript@7.13.0`、`react-markdown@10.1.0`、`remark-gfm@4.0.1`，committed OpenAPI/generated contract 无工作区差异。
- committed OpenAPI 再次确认 detail 200 为 arbitrary object、Initial React TaskPlan routes 422 为 `HTTPValidationError`、confirm-stream 200 为 generic `RagSseEventFrame`；真实 backend Route/Schema/domain/exception handler/tests 与 CG004-CG006 Evidence 一致。
- 修改前 `pnpm contracts:check` 通过；backend `test_agent_task_plan_list.assert_http_contract()`、`test_rag_stream_contract.py` 与 `test_schema_field_descriptions.py` 通过。这些 baseline 证明现有 list/envelope/schema-description 回归稳定，但不关闭三项 gap。
- 用户于本轮确认理解三项问题并批准继续执行 active Execution Plan；该指令批准当前唯一 Next Action 下 CG004-CG006 的严格受限 backend contract fix。修复范围保持 Recommended Backend Change，不扩展 executor、状态机、真实工具行为、非流式 `/confirm`、legacy Chat、Admin/Grant 或未来 Slice Route。
- 计划恢复 checkpoint `f288b6d` 只记录 Context Recovery 与 CG004-CG006 授权，没有混入 backend 或外部 evaluation working set。
- 在 CG004 expected-red fixture 准备中复核 Feature Spec ownership seam：无敏感真实 Route probe 证明他人 plan 返回 `403 / TOOL_PERMISSION_DENIED`，missing plan 的当前通用 store failure 返回 `400 / APP_SERVICE_ERROR`；Route 与 executor/repository 源码同时确认 system admin bypass 或 owner mismatch 403。该事实与 Feature Spec 的统一隐藏式 404 冲突，提升为 CG007。
- 发现 CG007 后未创建或修改任何 backend/frontend业务源码或测试。恢复后的唯一 Next Action 改为等待 CG007 严格受限授权；CG004-CG006 保持已批准但暂停。
- 用户于 2026-08-28 明确批准 CG007 Recommended Backend Change。短恢复确认 HEAD `9e2188f98f1641cafcf9d0da248cb05c8a6c0d4e`，tracked unstaged/staged diff 为空；8 个 backend evaluation 未跟踪文件仍属于外部 working set并继续排除。唯一 Next Action 是从 detail HTTP expected-red 开始，不重做已完成 Slice。

Context Recovery Evidence (verified 2026-08-28 after quota interruption):

- confirmed HEAD 为 CG007 授权 checkpoint `0fd1486da45b3d4c56feb57c097e25b69b9c0c35`；frontend scoped diff 与全部 staged diff 为空。backend working set 只有 `agent_task_plan_routes.py`、`services/exceptions.py` 和新 `test_agent_task_plan_resource_visibility_contract.py`，另有 8 个明确排除的 evaluation 未跟踪文件。
- 完整 diff 证明 working set 只新增稳定 `AGENT_TASK_PLAN_NOT_FOUND`、Route 层 `_load_owned_public_plan()`、detail 对该 resolver 的使用和公开 HTTP contract test；没有修改 executor、store、状态机、非流式 `/confirm`、真实工具行为或 frontend。
- 恢复运行 `test_agent_task_plan_resource_visibility_contract.py` 通过：missing、普通 other-owner 与 system-admin other-owner 均为相同 `404 / AGENT_TASK_PLAN_NOT_FOUND`，测试 marker 不回显；same-owner detail 为 200。
- 本计划原 Current Step/Next Action 已落后于 green working set。修正后的唯一 Next Action 是先为 Markdown Route 增加相同 owned-resource contract expected-red，再复用已建立 resolver 做最小实现；CG004-CG006 保持已批准但暂停于 CG007。

CG007 Completion Evidence (verified 2026-08-28):

- CG007 对 detail、Markdown、confirm-stream、cancel、retry 逐 Route 完成 expected-red → minimal green：missing、普通 other-owner 与 system-admin other-owner 均得到相同 `404 / AGENT_TASK_PLAN_NOT_FOUND` 和固定安全 message；测试 marker、TaskPlan ID、owner 与权限信息均不回显，同 owner 路径保持 200。
- Route preflight 只覆盖 Initial React 的五条公开 Route；未修改 executor、store、状态机、真实工具行为或非流式 `/confirm`，并新增非流式 `/confirm` 的 system-admin other-owner regression 证明该未授权范围行为保持不变。控制操作仍继续经过原 executor/repository 二次鉴权。
- 实际通过：`py_compile`（两个修改源码与新 contract test）、`test_agent_task_plan_resource_visibility_contract.py`、TaskPlan list HTTP contract、`test_rag_stream_contract.py`、`test_schema_field_descriptions.py`、Auth/Conversation/RAG Chat validation contract。
- 额外运行 `test_agent_task_executor_control_regressions.py` 时在既有 private test seam `_resume_locked()` 失败：fixture 未提供当前 executor 所需 `_document_access_policy`。本次 diff 未修改 executor 或该测试；该 test-harness drift 不影响公开 CG007 HTTP contract，按范围限制记录但不借机修复。
- 独立 backend checkpoint `3a14f4a` 只包含 `agent_task_plan_routes.py`、`services/exceptions.py` 和 `test_agent_task_plan_resource_visibility_contract.py`；外部 evaluation 未跟踪 working set 未被读取、修改或暂存。CG007 关闭，唯一 Next Action 恢复 CG004 的公开 detail contract expected-red。

CG004 Completion Evidence (verified 2026-08-28):

- `test_agent_task_plan_detail_contract.py` 先在 Document raw `AgentTaskPlan.model_dump()` 上 expected-red，再由显式 `DocumentTaskPlanPublicView`、安全 step/result-summary models、值级 risk allowlist 与 detail-only projection 转为 green。Research 继续复用既有 `ResearchTaskPlanPublicView`。
- runtime test 固定两种 `task_kind`、Document 精确字段 allowlist、Research internal fields 排除、raw input/output/error/final_output/owner/path/ACL/scope/trace marker 不回显；OpenAPI test 固定 `oneOf`、`task_kind` discriminator/mapping 和安全嵌套 schema properties。
- 最初复用共享 `_public_plan_payload()` 导致未授权非流式 `/confirm` response validation regression；随后拆出 detail 专用 `_public_detail_view()` 并保留原 helper 行为。CG007 resource visibility、Research v2、TaskPlan list HTTP、RAG SSE contract、schema descriptions 与非流式 `/confirm` regression 均通过。
- 独立 backend checkpoint `a24d53b` 只包含 detail Route、公共 response schema/projection 和 CG004 contract test。重新导出的 OpenAPI 保持 58 paths，只有 detail path operation 变化；schemas 从 88 增至 109，因为既有 Research Public View 嵌套类型首次进入 components。
- frontend contract sync checkpoint `04027f8` 只包含 snapshot/generated types；`pnpm contracts:generate`、`pnpm contracts:check`、typecheck 与完整 `pnpm check` 通过（19 files / 82 tests + production build）。dependency graph 未变化，browser smoke 对纯 contract sync 不适用。CG004 Runtime = OpenAPI = generated types = Tests，关闭并恢复 CG005。

CG005 Completion Evidence (verified 2026-08-28):

- `test_agent_task_plan_validation_contract.py` 先在 list runtime 缺少 `field_errors` 上 expected-red，再通过 Route+location+field allowlist 变绿：只允许 list query 的 `status`、`session_id`、`limit`，confirm-stream/cancel/retry 的固定 body/header validation 保持 `field_errors=[]`，marker 不回显。
- detail/Markdown/confirm-stream/cancel/retry 只注册安全 422 response model；Markdown 200 继续为 `text/plain`，其 422 显式为 `application/json`。非流式 `/confirm` 和无关 probe 继续使用原 `HTTPValidationError`/旧 runtime shape，未扩展到授权范围外 Route。
- Auth、Conversation、structured Chat 的 runtime 字段投影 regression 全部通过；其 OpenAPI exact-enum tests 只同步新增的三个获批公共字段。CG004 detail、CG007 visibility、TaskPlan list、RAG SSE 与 schema-description regressions 通过。
- 独立 backend checkpoint `c337db6` 只包含安全 validation handler、公共 field enum、六条 Route 声明和对应 contract regressions。frontend 重新导出后只有六条 TaskPlan path operation 变化，公共 field enum 为既有字段加 `status/session_id/limit`；checkpoint `1e6882f` 只包含 snapshot/generated types。
- contract generate/drift/typecheck 均通过。首次完整 `pnpm check` 在未修改的 Conversations create-navigation test 上观察到一次 `/chat` 未及时变为 `/chat/session-new`；单独重跑该 11-test file 通过，随后完整 `pnpm check` 通过（19 files / 82 tests + production build）。该一次性异步时序波动未通过修改 Conversations 或弱化断言处理。dependency graph 未变化，browser smoke 对纯 contract sync 不适用。CG005 Runtime = OpenAPI = generated types = Tests，关闭并恢复 CG006。

Slice 6 Contract Recovery Evidence (verified 2026-08-28):

- Slice 5 implementation checkpoint `633a07a` 与 Gate/state checkpoint `215761c` 已存在，恢复后 frontend/backend 共享 HEAD 为 `215761c1469d9bf7788fdfc4f370ef4a219c398c`，branch 为 `master...origin/master [ahead 23]`，工作树干净；最后 verified completed Slice 为 5。
- TaskPlan feature spec、相关 SPEC/Architecture/Development、frontend generated types/public SSE seam、backend AGENTS/required teaching rules、真实 Route/Schema/domain 和 focused tests 已读取。frontend 只有 `/tasks` placeholder、导航和 TaskPlan references，没有 `src/features/task-plans/` 或隐藏实现。
- backend list wrapper、opaque cursor、status/session filters、detail/Markdown、confirm-stream、cancel/retry 和 Idempotency-Key Route 均存在；`assert_http_contract()` 与 `test_rag_stream_contract.py` 通过，证明当前 list baseline 与 SSE envelope/request ID baseline，但不证明 detail discriminated schema、422 runtime/OpenAPI equality 或业务 event payload schemas。
- CG004：committed OpenAPI 对 `GET /agent/task-plans/{task_plan_id}` 的 200 schema 是 `type=object + additionalProperties=true`；generated transport 因此只有 `{[key:string]: unknown}`。runtime Route 对 Research 返回现有 `ResearchTaskPlanPublicView`，对 Document 直接返回内部 `AgentTaskPlan.model_dump()`；前者未进入 OpenAPI，后者包含 `user_id`、arbitrary step input/output、final_output 等内部结构，当前没有安全的两类 detail response union 或 runtime/OpenAPI regression test。
- CG005：committed OpenAPI 对 Initial React 使用的 list/detail/markdown/confirm-stream/cancel/retry 422 全部引用 `HTTPValidationError`。无敏感 TestClient probes 对 invalid list status/limit、invalid confirm body 与 missing cancel idempotency header 均得到 422，runtime keys 只有 `code/error_category/message/request_id/trace_id`，无 `detail`/`field_errors`，marker 未回显。
- CG006：confirm-stream 200 OpenAPI 只声明 `RagSseEventFrame {event:string,data:object}`；现有 contract test 只验证 envelope、request ID 和一个 `agent_task_execution_started` event。真实 `_task_plan_progress_events()` 会对部分 research/document progress 使用 arbitrary key spread，并在已知 step/sub-question events 中放入 arbitrary `output` 或 `tool_calls`；没有 TaskPlan 业务 event Pydantic schemas、safe projection 或 OpenAPI/test union，无法满足独立 typed reducer 与敏感 payload boundary。
- Repository/Git/Tests 与进入 Slice 6 时的计划记录一致；新发现只来自真实 backend contract。唯一 Next Action 是等待 CG004-CG006 backend contract fix 授权，不按内部 dict 猜 frontend DTO。

Context Recovery Evidence (verified 2026-08-28 after quota reset and editor-state discrepancy):

- frontend/backend 目录再次确认共享 Git root 与 HEAD `30dbfc891d462e803195cd1557184ce5b132b4ae`，branch 为 `master...origin/master [ahead 21]`；backend scoped unstaged/staged diff 为空，frontend 有 7 个 tracked modifications 与 3 个 untracked Markdown Viewer files，staged diff 为空。
- 最近 commits 仍包含 CG003 backend `d3d95ba`、frontend contract sync `3a7f198`、Slice 5 non-Markdown core `1444099` 与依赖 blocker plan `30dbfc8`；Repository 没有回退，最后 verified completed Slice 仍为 Slice 4 checkpoint `5821b25`。
- 当前 package/lockfile 已精确解析 `react-markdown@10.1.0` 与 `remark-gfm@4.0.1`；committed OpenAPI snapshot/generated types 自 `3a7f198` 后无差异，`pnpm contracts:check` 通过。
- Markdown Viewer 与 Conversations focused tests 为 2 files / 12 tests 通过；`pnpm typecheck`、全量 19 files / 82 tests 与 production build 分别通过。完整 `pnpm check` 在 lint 阶段因 `MarkdownViewer.tsx` render 内定义 link renderer 的 `react(no-unstable-nested-components)` warning 失败。
- backend `test_rag_chat_validation_contract.py` 与 `test_rag_stream_contract.py` 通过，CG003 Runtime/OpenAPI/tests 仍一致。dependency audit 首次尝试因受限环境访问 npm audit endpoint 得到 `EACCES`，未形成成功证据。
- 本计划原 Current Step/Next Action、Current Working Set 与 KI003 已落后于工作区；恢复后唯一 Next Action 是先修复上述 lint Gate，再继续同一 Slice 的 Gate，不开始 Slice 6。

Context Recovery Evidence (verified 2026-08-27 after explicit CG003 authorization and session recovery):

- frontend 与 backend 目录重新确认共享 Git root `D:/AI_Agent_Project`，共同 confirmed HEAD 为 `a25293fe395b51dd88a7966bfcab40bed21b35ea`，branch 为 `master...origin/master [ahead 16]`；两边 `git status --short --branch` 除 branch 行外无输出，完整 unstaged/staged diff 及 stat 均为空。
- 最近 commits 与 checkpoint 链一致：CG002 backend `2a13eb3`、Slice 4 frontend `5821b25`、Slice 4→5 状态转换 `d276d12`、CG003 blocker plan `a25293f`。`5821b25..HEAD` 的 frontend `src`/package/lockfile 无差异，`2a13eb3..HEAD` 的 backend `src`/tests 无差异；最后 verified completed Slice 仍为 4。
- Slice 4 的 `ConversationsWorkspace`、conversation API/query/model、真实 `ChatPage` 和 `/chat`、`/chat/:sessionId` route 均存在；`src/features/chat/` 不存在，确认 Slice 5 feature implementation 尚未被未记录地开始。
- 当前 package 精确保留 pnpm `10.32.1`、`openapi-typescript` `7.13.0`、TypeScript `6.0.3` 与 jsdom `29.1.1` 的现有解析；lockfile 未变化。committed snapshot 为 OpenAPI `3.1.0` / 58 paths / 88 schemas，generated header 仍声明禁止手工修改。
- frontend focused recovery baseline 为共享 HTTP/SSE/Conversations 5 files / 30 tests 全部通过。backend `.venv` 下 Chat stream、Auth validation、Conversation validation 与 schema field-description contract scripts 全部通过。
- 当前 `pnpm check` 通过 generated drift、lint、typecheck、15 files / 66 tests 与 production build；该结果与 Slice 4 checkpoint 记录一致。
- 无外部依赖的当前 Runtime/OpenAPI 探针再次确认 CG003：空白 `query` 请求返回 `422`，runtime keys 只有 `code/error_category/message/request_id/trace_id`，无 `field_errors`/`detail`，测试 marker 未回显；committed OpenAPI 422 仍引用 `#/components/schemas/HTTPValidationError`。
- 本计划过期的“等待授权”、Current Working On/Next Action、未勾选的已完成 reconnaissance、错误 Schema 路径和缺失的当前恢复证据已修正。Current Slice 保持 5 / BLOCKED；唯一 Next Action 是先新增严格受限的 CG003 expected-red backend contract test。

Context Recovery Evidence (verified 2026-08-26 after session change):

- frontend 与 backend 目录重新确认共享 Git root `D:/AI_Agent_Project`，共同 confirmed HEAD 为 `2f27d83aa50f67f0f8b04ef4c3d6bc338e247760`，branch 为 `master...origin/master [ahead 11]`。
- 恢复开始时从 frontend 与 backend 目录分别运行 `git status --short --branch`；除 branch 行外无输出。两边的完整 unstaged diff、staged diff 及其 stat 均为空。
- 最近 commits 与计划中的 checkpoint 链一致：Slice 1 `7cdbcaa`、backend CG001 `313d634`、Slice 2 `265e900`、Slice 3 `c324170`、进入 Slice 4 `77e4cfc`、记录 CG002 `2f27d83`。最后一个真正完成并含业务实现的 Slice 是 Slice 3；`2f27d83` 只修改本计划。
- `c324170..HEAD` 的 frontend `src`、package 和 lockfile 无差异；`e532197..HEAD` 的 committed OpenAPI snapshot、generated contract、package 和 lockfile 无差异；`313d634..HEAD` 的 backend `src` 与相关 tests 无差异。当前 Slice 1-3 checkpoint 对应源码仍存在。
- 当前 `src/app/App.tsx` 的 `/chat` 与 `/chat/:sessionId` 仍装配 `PlaceholderPage`；Repository 中没有 `src/features/conversations/`，也没有 Conversations transport、TanStack Query 或页面数据流，未发现 Slice 4 被未记录地继续实施。
- 当前 package manifest/lockfile 实际解析 Node `24.14.0`、pnpm `10.32.1`、`openapi-typescript` `7.13.0`、TypeScript `6.0.3` 和 jsdom `29.1.1`。committed OpenAPI snapshot 为 `3.1.0` / 58 paths / 88 schemas，generated header 标明禁止手工修改；`pnpm contracts:check` 通过。
- frontend focused recovery tests 为 7 files / 30 tests 全部通过。随后 `pnpm check` 通过 generated drift、lint、typecheck、12 files / 54 tests 与 production build。
- backend `.venv` 下 `test_conversation_management.assert_http_contract()`、`test_auth_validation_contract.py` 与 `test_schema_field_descriptions.py` 通过。Conversation TestClient runtime/OpenAPI 探针重新确认 POST/PATCH 空白 `title` 都返回 `422`，runtime keys 只有 `code/error_category/message/request_id/trace_id`，两条 OpenAPI `422` 均引用 `HTTPValidationError`。首次探针打印 OpenAPI `$ref` 时发生 PowerShell 变量展开导致探针自身 `KeyError`；改用无 `$` 插值的读取方式后重跑成功，不是后端失败。
- 本计划主状态与仓库事实一致：Last verified completed Slice 为 3；Current Slice 为 4 / BLOCKED；CG002 仍真实存在。恢复后唯一 Next Action 仍是等待用户明确授权或拒绝推荐的严格受限 backend contract fix；本轮不继续编码。

Historical Context Recovery Evidence (verified 2026-08-25 after manual context compaction):

- 恢复开始时 confirmed HEAD 为 `6d3bc71`；frontend 与 backend 位于同一 Git root `D:/AI_Agent_Project`，branch 为 `master...origin/master [ahead 3]`。
- `git status --short --branch` 除 branch 行外无输出；`git diff --stat`、完整 unstaged diff、`git diff --cached --stat` 与完整 staged diff 全部为空。
- Slice 0 文档治理 checkpoint 为 `dfa5b7a`，计划批准/进入 Slice 1 的状态转换 checkpoint 为 `768b6d8`；Slice 1 checkpoint 为 `7cdbcaa`；CG001 blocker checkpoint 为 `6d3bc71`。
- Slice 1 protocol infrastructure 真实存在：`contracts/backend-openapi.json`、generated transport types、generated drift script、共享 HTTP/error/media-type seam、SSE byte framer、Public Event validation/safe projection/terminal semantics 及其 deterministic tests 均在 Repository 中；`package.json` 精确包含 `openapi-typescript` `7.13.0` 和 contract scripts。
- `pnpm contracts:check` 通过；`pnpm test` 为 4 files / 17 tests 全部通过。
- 后端 `test_auth_identity_capabilities.py` 通过；`test_auth_session_security.py::assert_http_contract` 通过。首次缺少 `PYTHONPATH=src` 的命令环境错误已按后端文档修正后重跑，不作为代码失败。
- 真实 Auth router + 全局 exception handler + overridden external AuthService seam 对空 `/auth/login` JSON 返回 `422` 和 `REQUEST_VALIDATION_ERROR`，runtime keys 只有 `code/error_category/message/request_id/trace_id`；三个 Auth route 的 OpenAPI `422` 仍引用带 `detail` 的 `HTTPValidationError`。
- Current Slice/Status 与 blocker checkpoint 一致：Slice 2 / BLOCKED；CG001 仍真实存在。用户已在本次恢复条件满足后授权推荐 backend fix；唯一 Next Action 是 test-first 修复该 contract，不扩大 backend scope。
- 恢复后的文档 checkpoint 为 `1ae0d57`；独立 backend CG001 checkpoint 为 `313d634`。backend fix 后重新导出的 snapshot 为 58 paths / 88 schemas，generated drift 与 TypeScript typecheck 通过；CG001 已关闭，Slice 2 现恢复为 IN_PROGRESS。
- Slice 2 实施后的 frontend checkpoint 为 `265e900`；`pnpm check` 通过 10 files / 47 tests 与 production build，manual browser smoke 通过。checkpoint 后除本计划的 Slice 2→3 状态转换外工作树无其他修改，Current Slice 现为 3。
- Slice 3 实施后的 frontend checkpoint 为 `c324170`；`pnpm check` 通过 12 files / 54 tests 与 production build，authenticated manual browser smoke 通过。checkpoint 后除本计划的 Slice 3→4 状态转换外工作树无其他修改，Current Slice 现为 4。
- Slice 4 contract recovery 时 confirmed HEAD 为 `77e4cfc`，frontend/backend 共用 working tree 干净；backend `.venv` 下 `test_conversation_management.assert_http_contract()` 通过。误用系统 Python 导致缺少 FastAPI 的环境错误已按仓库虚拟环境修正重跑，不作为代码失败。
- 无敏感值 TestClient 复现 `POST /conversations` 与 `PATCH /conversations/{session_id}` 空白标题均返回 `422`，runtime keys 只有 `code/error_category/message/request_id/trace_id`；两条 OpenAPI `422` 均引用带 `detail` 的 `HTTPValidationError`。CG002 已确认，Current Slice 现为 4 / BLOCKED。

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

### KI001 - Business Implementation Had Not Started

Status: RESOLVED / SUPERSEDED

Evidence:

- Slice 1 已在 checkpoint `7cdbcaa` 完成 contract snapshot、generated transport types、共享 HTTP/error seam 与 SSE protocol infrastructure，并以 4 files / 17 tests 和 `pnpm check` 验证。
- Slice 2 随后已在 checkpoint `265e900` 完成 AuthProvider、token lifecycle、认证表单与路由保护，10 files / 47 tests 和 browser smoke 通过；Slice 3 已在 checkpoint `c324170` 完成，Slice 4 已在 checkpoint `5821b25` 完成，当前已进入 Slice 5。

Impact:

- 原“所有业务 Slice 均 NOT_STARTED”的实施前警示不再适用；当前进度由本计划的 Slice 状态、Git checkpoints 和实际测试共同证明。

Resolution:

- 由 Slice 1 checkpoint `7cdbcaa` supersede；CG001 已由 backend checkpoint `313d634` 关闭，Slice 2 已由 frontend checkpoint `265e900` 完成，Slice 3 已由 frontend checkpoint `c324170` 完成，CG002 已由 backend checkpoint `2a13eb3` 关闭，Slice 4 已由 frontend checkpoint `5821b25` 完成，当前为 Slice 5 / IN_PROGRESS。

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

Status: RESOLVED IN SLICE 5

Evidence:

- `react-markdown@10.1.0` 与 `remark-gfm@4.0.1` 已按用户批准精确写入 package/lockfile；没有安装 `rehype-raw`。
- 共享 `MarkdownViewer` 使用 `skipHtml`、图片丢弃和 credential-free HTTP(S) link renderer；安全 DOM test 已覆盖 GFM、raw HTML、图片、凭据 URL 与脚本 URL。

Impact:

- 原 dependency decision gap 已关闭；当前只剩普通 Slice Gate verification，不再构成依赖阻塞。

Resolution:

- 采用已批准的精确版本与安全配置；focused/full tests、production build、dependency audit 和 browser smoke 均通过，frontend checkpoint `633a07a` 已持久化实现。

### KI004 - No Automated E2E Framework

Status: APPROVED CONSTRAINT / NON-BLOCKING

Evidence:

- 当前工具链为 Vitest、jsdom、React Testing Library 和 MSW，没有 Playwright/Cypress。

Impact:

- 关键浏览器流程需要人工 smoke evidence，不能声称自动 E2E coverage。

Resolution:

- 按每个浏览器可见 Slice 与最终 Slice 的 manual smoke gate 执行；未经批准不增加 E2E 依赖。

### KI006 - Future Mutation 422 Contract Inventory

Status: INVENTORIED / CHAT QUERY RESOLVED AS CG003 / TASKPLAN RISKS ELEVATED TO CG004-CG006

Evidence:

- 按用户授权只读检查 Initial React 后续 Slice 实际使用的 mutation endpoints；当前 OpenAPI snapshot 中 `POST /rag/chat/stream/events`、`POST /agent/task-plans/{task_plan_id}/confirm/stream`、TaskPlan cancel/retry、`POST /admin/users`、`PUT /admin/users/{user_id}/access`、`PATCH /admin/users/{user_id}/status`、`POST /admin/users/{user_id}/reset-password`、`POST /admin/document-access/grants` 和 grant DELETE 的 `422` 均仍引用 `#/components/schemas/HTTPValidationError`。
- 对应 backend Route/Pydantic Schema 仍由全局 `RequestValidationError` handler 处理，但不在 CG001/CG002 明确批准的 field allowlist 内；因此 runtime validation 使用公共 form-level `code/message/error_category/request_id/trace_id` shape，而 OpenAPI 仍声明 FastAPI `detail[]` shape。
- 使用真实 admin user / document grant router、全局 handler 和 overridden service 的无敏感 TestClient 代表性验证：空 `POST /admin/users` 与空 `POST /admin/document-access/grants` 均返回 `422`，runtime keys 为 `code/error_category/message/request_id/trace_id`。
- User Management feature 明确要求把 `422` 映射到 account、primary department、roles、permissions 等字段；全局 SPEC 对表单 `422` 也要求字段级错误。Chat、TaskPlan、Document Grant 的实际字段映射需求仍须在各自 Slice 结合真实交互重新判定。
- Slice 6 reconnaissance 已确认 TaskPlan 不只有 422 drift：detail 200 仍为 arbitrary object，confirm-stream 也只有 generic envelope 且缺少业务 payload schema；对应问题已分别提升为 CG004-CG006。

Impact:

- Slice 8 User Management 是高可信未来 contract risk；Slice 9 Document Access Grants 是待对应 Slice 核实的潜在风险。Slice 6 已实际复核并确认 detail type、422 drift 与 business event schema 都直接阻塞安全 typed frontend implementation。
- Slice 5 reconnaissance 已确认 `query` 字段确实受影响，因此该部分风险已提升为正式 blocking CG003；其他未来 Route 仍只保留 inventory 状态。
- inventory 未发现新的 Slice 4 Route gap；因此它不阻塞 Slice 4，也不授权提前修改任何未来 backend Route。

Resolution:

- 仅记录风险。进入对应 Slice 时重新执行 Route/Schema/OpenAPI/runtime/spec 核对；只有确认影响该 Slice 的公开行为后，才建立精确 Contract Gap 并按 Blocking Condition 请求受限授权。
- 禁止把 CG001/CG002 授权外推到上述 Route，禁止现在预修复。
- Chat `query` 风险已由严格受限的 CG003 backend checkpoint `d3d95ba` 解决；TaskPlan 风险已提升为 CG004-CG006 并等待单独授权，Admin 与 Grant 风险仍保持 inventory，未被任何当前授权覆盖。

### Contract Gaps

#### CG001 - Auth 422 Field Error Schema Does Not Match Runtime

Status: RESOLVED IN SLICE 2

Evidence (pre-fix and closure):

- `docs/features/authentication/feature.md` 第 5 节要求 `422` 字段错误显示在对应输入框。
- 修复前 OpenAPI 对 `/auth/login`、`/auth/refresh`、`/auth/change-password` 的 `422` response 都引用 `#/components/schemas/HTTPValidationError`；该 schema 的 `detail[]` 声明了 `loc`、`msg` 和 `type`。
- 修复前 `fast_app.core.exception_handlers.handle_request_validation_error()` 调用 `build_error_response_content()`，实际 runtime 只返回 `code`、`message`、`error_category`、`request_id`、`trace_id`。
- 2026-08-25 TestClient 对 `POST /auth/login` 提交空 JSON 得到 `422`、`code=REQUEST_VALIDATION_ERROR`，响应 keys 正是上述五项，`detail`/字段位置不存在。
- 后端 `test_auth_identity_capabilities.py` 与 `test_auth_session_security.py::assert_http_contract` 通过，但它们不覆盖 validation field locations；因此现有成功测试不能证明 Feature spec 的 field mapping contract。
- backend checkpoint `313d634` 新增 `RequestValidationErrorResponse` / `RequestValidationFieldError`，OpenAPI 将公开 field/code 固化为 enum allowlist。
- 全局 handler 只对 `POST /auth/login`、`POST /auth/refresh`、`POST /auth/change-password` 的顶层公开字段投影固定 code/message；不读取或回显 error `input`/`ctx`，无法映射时 `field_errors=[]`，非 allowlisted route 保持原响应 shape。
- `test_auth_validation_contract.py` 先以缺失 schema expected-red，修复后验证三个 route runtime/OpenAPI、敏感输入不回显、form-level fallback、非 Auth route 不变及 schema enum；相关 backend regressions 全部通过。
- frontend snapshot/generated types 已从 backend commit `313d634` 更新；三个 Auth 422 transport response 均引用 `RequestValidationErrorResponse`，`pnpm contracts:check` 与 `pnpm typecheck` 通过。

Impact before resolution:

- 修复前 React 无法从服务端 `422` 确定 `username_or_email`、`password`、`current_password` 或 `new_password` 中哪个字段失败。
- 修复前按 OpenAPI generated type 读取 `HTTPValidationError.detail` 会与 runtime 不符；猜测字段或仅显示 form-level error 都不能满足已批准 Feature spec。
- 该阻塞影响现已消除；Slice 2 可使用 generated transport type 和安全 `field_errors` 实现字段映射，不需要猜测 Pydantic 原始结构。

Implemented Backend Change:

- 在后端定义稳定、前端安全的公共 validation error response schema，为每个可展示字段提供 allowlisted `field`、`code`、`message`，同时保留顶层 `code/message/error_category/request_id/trace_id`。
- `handle_request_validation_error()` 从 Pydantic/FastAPI `exc.errors()` 只投影公开请求字段，不回显 input、密码、token 或任意 context；所有其他位置保留 form-level error。
- 为相关 Route 显式声明同一 `422` response model，使 OpenAPI 与 runtime 一致，并增加 Auth HTTP contract regression tests；随后重新导出 frontend snapshot/generated types。

Decision:

- 用户已于 2026-08-25 批准推荐方案，并把 backend 修改范围严格限定为安全公共 RequestValidationError schema、全局 handler 的 allowlisted field projection、Auth route 422 OpenAPI 声明与对应 tests。
- 禁止回显 `input`、password、token、secret 或任意敏感值；field 只能来自明确公开请求字段 allowlist，无法安全映射的错误保留 form-level。
- backend fix 必须独立 checkpoint；随后重新导出 frontend OpenAPI snapshot/generated types、运行 drift check、验证 OpenAPI/runtime/tests 一致后才能将 CG001 标为 RESOLVED 并恢复 Slice 2。

Resolution:

- 独立 backend checkpoint：`313d634`。
- frontend snapshot/type regeneration 与 drift check 已完成；CG001 已重新验证关闭，Slice 2 状态恢复为 `IN_PROGRESS`。

#### CG002 - Conversation 422 Field Error Schema Does Not Match Runtime

Status: RESOLVED IN SLICE 4

Evidence:

- `docs/SPEC.md` 第 7 节要求 `422` 映射到字段错误；Slice 4 的创建与重命名表单均包含公开 `title` 字段。
- `CreateConversationRequest` 与 `UpdateConversationRequest` 都会拒绝纯空白标题；backend `test_conversation_management.assert_http_contract()` 验证 rename 空白标题返回 `422`，其余会话 HTTP route baseline 通过。
- 2026-08-26 Context Recovery 使用真实 Conversation router、全局 exception handler 与 overridden service 的 TestClient，以无敏感空白标题请求 `POST /conversations` 和 `PATCH /conversations/contract-session`，两者 runtime 均返回 `422`，response keys 只有 `code/error_category/message/request_id/trace_id`；同日 backend Conversation HTTP contract test 重新通过。
- 同一 app 的 OpenAPI 对上述两个 `422` response 均引用 `#/components/schemas/HTTPValidationError`，声明 `detail[].loc/msg/type`；runtime 与 OpenAPI 不一致，也没有可供 React 安全映射到 `title` 的 `field_errors`。
- CG001 的 backend 授权严格限定 Auth route；现有 `RequestValidationErrorResponse` allowlist 也只包含 Auth 公开字段。该授权不能外推到 Conversations。

Impact:

- React 若按 generated OpenAPI 读取 `HTTPValidationError.detail` 会与 runtime 不符；若只显示 form-level error，又不满足批准的通用 `422` 字段映射要求。
- 受影响范围是 Conversation create/rename 表单与其 deterministic contract tests。Cursor list、messages 和 delete contract 本身已确认，但 Slice Gate 要求一个完整 coherent Slice，不能绕过受影响行为后标记完成。

Recommended Backend Change:

- 复用 CG001 的安全公共 validation response model，仅将 `title` 加入明确公开字段 allowlist，并为 Conversation `POST`/`PATCH` 的顶层 body `title` 投影固定 public code/message。
- 不读取或回显 Pydantic/FastAPI error 的 `input`、`ctx` 或原始 `msg`；path/session_id 等无法安全映射的 validation error 保持 `field_errors=[]` 的 form-level response。
- 为两个受影响 Conversation route 显式声明同一 `422` response model，并增加 runtime/OpenAPI/no-input-echo/non-allowlisted-route regression tests。
- 修复必须是独立 backend checkpoint；随后重新导出 frontend OpenAPI snapshot/generated types，运行 drift check，并在本计划记录 backend commit 后关闭 CG002。

Decision:

- 用户已于 2026-08-26 明确授权上述严格受限的 backend contract fix。授权只覆盖两个 Conversation Route 的 `title` 安全字段投影、422 OpenAPI 声明及对应 runtime/OpenAPI/no-sensitive-echo/regression tests，不得外推到未来 Route。
- backend fix 必须独立 checkpoint；Runtime = OpenAPI = Tests 并同步 frontend snapshot/generated types 后才能关闭 CG002 并恢复 Slice 4 frontend implementation。

Resolution:

- backend 独立 checkpoint `2a13eb3` 完成 `title` allowlist、两个 Conversation Route 422 schema 和安全 projection；未扩展到其他 Route。
- 新增 `test_conversation_validation_contract.py` 覆盖 POST/PATCH runtime、OpenAPI、敏感 marker 不回显、malformed body、path validation form-level fallback 和非 allowlisted Route regression；既有 Auth validation enum expectation同步增加已批准的 `title`。
- frontend snapshot/generated types 已从 `2a13eb3` 重新导出和生成；`pnpm contracts:check`、typecheck 与 `pnpm check` 通过，Runtime = OpenAPI = Tests，CG002 关闭，Slice 4 恢复为 `IN_PROGRESS`。

#### CG003 - Structured Chat 422 Field Error Schema Does Not Match Runtime

Status: RESOLVED IN SLICE 5

Evidence:

- `docs/SPEC.md` 第 7 节要求 `422` 映射到字段错误；Chat feature 的主输入是公开 `RagChatRequest.query`，其 Pydantic schema 要求长度 1–500 并拒绝纯空白字符串。
- 当前唯一 React Chat Route `POST /rag/chat/stream/events` 未声明公共 `RequestValidationErrorResponse`；实际 OpenAPI 的 422 response 引用 `#/components/schemas/HTTPValidationError`，声明 FastAPI `detail[].loc/msg/type` shape。
- 2026-08-26 使用当前 `RagChatRequest`、全局 `register_exception_handlers()` 和同一路径的无外部依赖 TestClient，对空白 `query` 加无敏感 marker 请求得到 `422`；runtime keys 只有 `code/error_category/message/request_id/trace_id`，marker 未回显，`field_errors`/`detail` 均不存在。
- `_VALIDATION_FIELDS` 只允许 CG001 Auth routes 与 CG002 Conversation POST/PATCH；Chat Route 不在 allowlist。CG001/CG002 的用户授权均严格限定对应 Route，不能外推。
- backend `scripts/tests/agent_research/test_rag_stream_contract.py` 当前通过，证明 SSE 200/public event/request ID/source baseline，但该测试不覆盖 request validation 422 runtime 或 OpenAPI schema，因此不能关闭此 gap。

Impact:

- React 若按 generated OpenAPI 读取 `HTTPValidationError.detail` 会与 runtime 不符；若只显示 form-level error，公开 `query` 又无法按批准的通用规则映射到问题输入框。
- 受影响的是 Slice 5 的 Chat request form、pre-stream `ApiError` 和对应 deterministic contract tests。现有 SSE parser/public event infrastructure 本身仍通过，但 coherent Slice 5 Gate 不能在该契约冲突下完成。

Recommended Backend Change:

- 复用 CG001/CG002 的安全公共 `RequestValidationErrorResponse`，只把公开顶层字段 `query` 加入明确 field allowlist，并只为 `POST /rag/chat/stream/events` 投影固定 public code/message。
- `session_id`、交叉字段/model-level、嵌套 `filters`、未批准字段及其他无法安全映射的位置保持 `field_errors=[]` 的 form-level response；本次推荐不扩展到 legacy `/rag/chat`、`/rag/chat/stream`、TaskPlan 或未来 Admin/Grant Route。
- 不读取或回显 validation error 的 `input`、`ctx` 或原始 `msg`，不暴露 query 内容、Dataset 值、token、secret、ACL、内部信息或未知字段名；field 只能来自明确批准的 `query` allowlist。
- 为 structured Chat Route 显式声明同一 422 response model，并增加 runtime/OpenAPI/no-sensitive-echo/form-level fallback/non-allowlisted-route regression tests。
- 修复必须是独立 backend checkpoint；随后重新导出 frontend OpenAPI snapshot/generated types，运行 contract drift 与必要回归，确认 Runtime = OpenAPI = Tests 后关闭 CG003 并恢复 Slice 5。

Decision:

- 用户已于 2026-08-27 明确授权上述严格受限的 backend contract fix。授权只覆盖 `POST /rag/chat/stream/events` 的公开顶层 `query` 安全字段投影、422 OpenAPI 声明与 runtime/OpenAPI/no-sensitive-echo/form-level fallback/non-allowlisted-route regression tests，不得外推到 legacy Chat、TaskPlan 或未来 Admin/Grant Route。
- CG003 修复必须保持独立 backend checkpoint；Runtime = OpenAPI = Tests 并同步 frontend snapshot/generated types 后才能关闭 CG003、把 Slice 5 恢复为 `IN_PROGRESS` 并开始依赖该契约的 frontend implementation。

Resolution:

- 独立 backend checkpoint `d3d95ba` 只修改安全公共 field enum、structured Chat Route allowlist/422 声明和对应 contract regressions；`query` 不回显，malformed body、`session_id`、嵌套 `filters`、model-level 与未批准字段保持 `field_errors=[]`，legacy `/rag/chat` 和 `/rag/chat/stream` runtime/OpenAPI 均未扩展。
- frontend snapshot/generated types 已从 `d3d95ba` 重新导出和生成；OpenAPI 仍为 58 paths / 88 schemas，`pnpm contracts:check`、lint、typecheck、15 files / 66 tests 与 production build 通过。Runtime = OpenAPI = Tests，CG003 关闭，Slice 5 恢复为 `IN_PROGRESS`。

#### CG004 - TaskPlan Detail Response Lacks a Safe Discriminated Contract

Status: RESOLVED IN SLICE 6

Evidence:

- TaskPlan feature 要求详情 adapter 先按 `task_kind` 区分 research 与 document 两种完整 Domain Model；Architecture 要求普通 HTTP DTO 来自 generated OpenAPI transport type，Component/Feature 不得自行定义漂移 DTO。
- `GET /agent/task-plans/{task_plan_id}` 当前 annotation 只是 `dict[str, Any]`，OpenAPI 200 是 `type=object + additionalProperties=true`，generated TypeScript 因此只有 `{[key:string]: unknown}`，没有 `task_kind` discriminator 或任何类型字段。
- Research runtime 已有明确的安全 `ResearchTaskPlanPublicView`，但 Route 未声明它，因此该 schema 完全未进入 OpenAPI snapshot。
- Document runtime 由 `_public_plan_payload()` 直接返回内部 `AgentTaskPlan.model_dump()`；该 internal model 包含 `user_id`、step arbitrary `input/output`、`final_output` 和其他不能直接当长期 frontend contract 的结构。当前没有安全 Document public view、两类 response union 或 no-sensitive-echo/detail OpenAPI regression test。

Impact:

- Frontend 无法遵守 generated transport type boundary 实现两种详情；若根据当前 runtime dict 手写 DTO，就会把内部 model 当公共长期契约并可能接收 Tool 参数、ACL/Scope 或其他敏感内部字段。
- TaskPlan list 与 Markdown text 本身可读取，但 coherent Slice 6 必须包含详情、状态 controls 与恢复，不能绕过 detail 后标记 Gate 完成。

Recommended Backend Change:

- 复用现有 `ResearchTaskPlanPublicView`，为 `knowledge_document_management` 定义显式 allowlisted 的安全 Document TaskPlan public view；保留批准的用户可见步骤、状态、风险、确认需求、结果摘要和错误码，但排除 `user_id`、raw Tool input/output/arguments、ACL、scope、lease/checkpoint、内部 trace 和未审核 arbitrary dict。
- 为 detail Route 声明以 `task_kind` 为 discriminator 的公共 response union，并让 runtime 通过同一 public projection 返回；不得改变 ownership/404、执行器、持久化或其他 Route 行为。
- 增加两种 task kind 的 runtime/OpenAPI/generated-discriminator/no-sensitive-field/ownership regression tests；创建独立 backend checkpoint 后重新导出 frontend snapshot/types。

Decision:

- 用户已于 2026-08-28 批准上述严格受限的 TaskPlan detail contract fix；只允许安全 detail public view/discriminated response、runtime/OpenAPI/no-sensitive/ownership tests，不得修改执行器、持久化、授权语义或其他 Route。

Resolution:

- backend checkpoint `a24d53b` 复用 Research 安全 Public View，并为 Document detail 建立显式 allowlisted view、步骤安全元数据、计数结果摘要、稳定 error code 与风险值投影；detail 200 OpenAPI 使用 `task_kind` discriminated `oneOf`，内部 owner/query/path/input/output/error/final_output 等字段不进入响应。
- frontend contract sync checkpoint `04027f8` 已重新导出 58 paths / 109 schemas snapshot 并生成两种判别 transport types；backend focused regressions、`pnpm contracts:check` 与完整 `pnpm check` 通过。CG004 Runtime = OpenAPI = generated types = Tests，关闭该 gap。

#### CG005 - TaskPlan 422 Schema Does Not Match Runtime

Status: RESOLVED IN SLICE 6

Evidence:

- Initial React 实际使用 `GET` list/detail/markdown 与 `POST` confirm-stream/cancel/retry；这些 Route 当前 OpenAPI 422 全部引用 `#/components/schemas/HTTPValidationError`，声明 FastAPI `detail[]`。
- 当前全局 validation handler 未为 TaskPlan Route启用安全 projection。TestClient 对 invalid list `status`/`limit`、invalid confirm body 和缺失 cancel `Idempotency-Key` 均返回 422，runtime keys 只有 `code/error_category/message/request_id/trace_id`，没有 `detail` 或 `field_errors`；测试 marker 未回显。
- 既有 `test_agent_task_plan_list.assert_http_contract()` 只断言 422 status，`test_rag_stream_contract.py` 只断言 SSE 200 envelope；二者均通过但不证明 422 OpenAPI/runtime equality。

Impact:

- Generated response type与 runtime 不一致；list filter field error、confirm pre-stream failure 和 control error 不能按 approved ApiError/field mapping contract安全处理。
- path、Idempotency-Key 和固定 `confirmed=true` 不是应回显的用户字段，不能通过暴露原始 validation detail 解决。

Recommended Backend Change:

- 复用 CG001-CG003 的安全公共 `RequestValidationErrorResponse`。只为 `GET /agent/task-plans` 的公开用户控制 filter `status`、`session_id`、`limit` 建立明确 allowlist；cursor、path、Idempotency-Key、固定 confirm body、model-level 与未知字段保持 `field_errors=[]`。
- 只为 Initial React 使用的 list/detail/markdown/confirm-stream/cancel/retry Route 声明同一 422 response model；不修改首期禁止调用的非流式 `/confirm`，也不扩展到 Admin/Grant 或其他 Route。
- 不读取或回显 validation `input`、`ctx`、raw `msg`、TaskPlan ID、Idempotency-Key、query、Tool 参数、ACL、secret 或内部字段；增加 runtime/OpenAPI/no-sensitive-echo/form-level/non-allowlisted regression tests。

Decision:

- 用户已于 2026-08-28 批准上述严格受限的 TaskPlan validation contract fix；只覆盖 Initial React list/detail/markdown/confirm-stream/cancel/retry Route 与 list 的 `status`、`session_id`、`limit` allowlist，不能外推到非流式 `/confirm`、Admin/Grant 或其他 Route。

Resolution:

- backend checkpoint `c337db6` 将安全投影配置扩展为 Route+location+field allowlist，只为 list query 公开 `status/session_id/limit`，其他五条 Route 的 path/header/fixed-body/未知错误保持 form-level；六条 OpenAPI 422 均声明 `RequestValidationErrorResponse`，非流式 `/confirm` 未改变。
- frontend contract sync checkpoint `1e6882f` 已重新导出并生成 types；路径级 diff 只包含六条授权 TaskPlan operation，shared Auth/Conversation/Chat regressions、contract drift 与最终 `pnpm check` 通过。CG005 Runtime = OpenAPI = generated types = Tests，关闭该 gap。

#### CG006 - TaskPlan Confirm Stream Business Events Lack Safe Public Schemas

Status: RESOLVED IN SLICE 6

Evidence:

- TaskPlan feature 与 Architecture 要求 confirm-stream 复用公共 envelope，但业务 event 必须进入独立 discriminated union/reducer；未知 payload 必须立即丢弃，已知 payload 也必须来自稳定公共 schema。
- 当前 OpenAPI 200 只声明 `RagSseEventFrame`，其中 `event` 是任意 string、`data` 是任意 object；`test_rag_stream_contract.py` 只验证 envelope/request ID 和单一 `agent_task_execution_started` payload。
- `_task_plan_progress_events()` 对部分 research/document progress 直接 spread arbitrary keys；step events包含 arbitrary `output`，legacy sub-question event包含 `tool_calls`。`_format_sse_event()` 只补 envelope，没有 per-event Pydantic validation或 safe projection。
- frontend 当前 central parser 只保留 task event name、request ID、received time 和 `task_plan_id` 的 safe reference，因此没有泄漏；但它也没有 Slice 6 reducer所需的稳定 status/progress fields，不能从 internal runtime dict 猜出长期 DTO。

Impact:

- 若直接把当前 payload 标成 known typed events，会把 Tool arguments/output、internal progress 或未来新增字段带入 UI/cache/log风险；若继续只保留 reference，又无法满足结构化进度、状态和独立 reducer验收。
- confirm-stream request isolation/envelope baseline 已可复用，但业务 event contract 未达到 Slice 6 implementation gate。

Recommended Backend Change:

- 只为 Initial React confirm-stream 实际展示的 TaskPlan progress/status/step/research/document events定义显式 Pydantic public event models 和 discriminated union；共享 `answer_delta`、`sources`、guard、`done/error` 继续复用既有公共 schema。
- Route在写 SSE 前必须通过对应 public model projection/validation，只保留批准的 IDs、稳定 status/error code、用户可见安全摘要和必要 progress facts；删除 raw arbitrary spread、step output、tool_calls、Tool arguments、ACL/Scope、Dataset rows、internal URL/trace 和未知字段。
- OpenAPI logical contract 与 backend tests必须覆盖 event name/payload schema、request ID/version、no-sensitive-field、unknown/internal event exclusion和两种 task kind代表事件；不改变 executor、TaskPlan状态机、真实工具执行或 legacy Chat stream。

Decision:

- 用户已于 2026-08-28 批准上述严格受限的 TaskPlan public SSE contract fix；只允许 confirm-stream 公共业务事件 models/projection/OpenAPI/tests，不改变 executor、TaskPlan 状态机、真实工具执行或 legacy Chat stream。

Resolution:

- backend checkpoint `2ca4bcc` 新增严格公共 event data/frame models、按事件名判别的 union 与 explicit safe projection；request-context ID 不能被 payload 覆盖，raw arbitrary progress/step/sub-question/tool/sensitive fields 与 unknown event 均在写 SSE 前丢弃。
- confirm-stream OpenAPI 通过 FastAPI response model 注册标准 components 引用；backend contract/no-sensitive/schema-description/shared regressions 与 frontend `openapi-typescript` generation 均通过。
- frontend contract sync checkpoint `d30d7ea` 只更新 OpenAPI snapshot/generated types；路径 diff 仅包含 confirm-stream 200，完整 `pnpm check` 通过。CG006 已关闭，Slice 6 恢复正常 frontend implementation。

#### CG007 - TaskPlan Ownership and Missing Resources Do Not Use the Required Hidden 404 Contract

Status: RESOLVED IN SLICE 6

Evidence:

- TaskPlan Feature Spec 第 5 节声明当前接口只允许用户读取和控制自己拥有的 TaskPlan，并要求已知他人 ID 的 `404` 不得泄露任务是否存在。
- 当前 detail/Markdown Route 先加载 plan，再允许相同 owner 或 `system_admin`；普通非 owner 抛出 `ToolPermissionDeniedError`。无敏感 TestClient probe 对他人 ID 得到 `403`、`code=TOOL_PERMISSION_DENIED`，与隐藏式 404 不符。
- 当前 repository 在 TaskPlan row 不存在时抛出通用 `AppServiceError("Agent task plan 不存在")`；同一真实 Route/handler seam 的无敏感 missing probe 得到 `400`、`code=APP_SERVICE_ERROR`，也与隐藏式 404 不符。
- confirm/retry 的 `_load_owned_plan()` 同样允许 `system_admin` 并对 owner mismatch 抛 403；cancel repository 对 missing 抛通用 400、对 owner mismatch 抛 403。Initial React 不使用非流式 `/confirm`，但 confirm-stream/retry/cancel 都受当前 ownership seam 影响。
- CG004 Recommended Backend Change 明确不得改变 ownership/404；CG004-CG006 的已批准范围只覆盖 response view、422 schema 与 SSE event projection，不能隐式授权新的权限/资源隐藏行为。

Impact:

- 前端若按 Feature Spec 将 404 作为统一不可见状态，当前 runtime 会通过 403/400 区分他人资源与缺失资源，形成资源枚举侧信道；同时 generated/runtime tests 无法建立已批准的 ownership 404 acceptance。
- CG004 的 detail runtime/ownership regression test 无法在不改变未授权 backend behavior 的情况下达到 green；因此当前 Slice 必须在业务编码前阻塞。

Recommended Backend Change:

- 为 Initial React 使用的 detail/Markdown/confirm-stream/cancel/retry 公共 Route 建立统一的 owned-resource resolution：missing 与 owner mismatch 均返回同一个稳定公共 404 code/message，且不在响应中泄露 TaskPlan ID、owner、权限或存在性。
- 仅对这些 Initial React Route 移除 public API 的 system-admin owner bypass；非流式 `/confirm`、内部 executor/state machine、真实工具执行、Admin/Grant 和其他 Route 不在本次范围。控制操作仍须在现有 executor/repository 边界二次鉴权，不能用 Route preflight 取代真实副作用前的授权。
- 增加 detail/Markdown/confirm-stream/cancel/retry 的 missing/other-owner/runtime/no-sensitive-echo regression tests；相同 owner 的正常行为、幂等、409、stream envelope 与所有已通过 regression 必须保持不变。

Decision:

- 用户已于 2026-08-28 批准上述严格受限的 TaskPlan resource-hiding contract fix；只覆盖 Initial React detail/Markdown/confirm-stream/cancel/retry 的 owned-resource resolution、统一安全 404 与对应 regressions，不覆盖非流式 `/confirm`、内部 executor/state machine、真实工具行为、Admin/Grant 或其他 Route。

Resolution:

- 独立 backend checkpoint `3a14f4a` 新增稳定 `AgentTaskPlanNotFoundError` 与 Route 层 owned-resource resolver；五条 Initial React Route 对 missing、普通 other-owner、system-admin other-owner 均统一为安全 `404 / AGENT_TASK_PLAN_NOT_FOUND`，same-owner 保持正常。
- runtime/no-sensitive-echo/regression contract test 与共享 Auth/Conversation/RAG validation、TaskPlan list、SSE envelope、schema-description baseline 均通过；非流式 `/confirm`、executor、store、状态机和真实工具实现未修改。CG007 Runtime = Tests，关闭该 gap 并恢复 CG004。

每个后续业务 Slice 仍须复核对应真实 Route/Schema/tests；如发现 drift，必须新增带 Evidence/Impact/Recommendation 的 gap 并停止受影响实现。

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

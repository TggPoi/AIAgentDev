# Initial React Frontend Execution Plan

## Status

Status: ACTIVE

Plan Approval: APPROVED BY USER ON 2026-08-25

Current Slice: 9 - Cross-Department Document Grants

Current Step: CG011已由backend `ea6df62`与frontend contract sync `03170c7`关闭；当前恢复Slice 9 grantable-document frontend data/query seam TDD

Next Action: 在既有Document Grants data focused test中新增grantable-document transport/domain/query expected-red，只固定新GET、safe fields、filters、opaque cursor与user-bound query key

Blocking Issues: None；CG011 Runtime = OpenAPI = generated types = Tests已闭环，create Dialog仍须在grantable-document data/query seam与draft policy分别验证后实施

Last Updated: 2026-09-01 (Asia/Shanghai)

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

Status: COMPLETED

Goal: 完成 TaskPlan 列表、详情、Markdown、确认流、取消、重试和恢复。

- [x] 读取 TaskPlan spec，复核 list wrapper、task-kind detail、控制接口、SSE 和 Idempotency contract。
- [x] 实现 list/detail/markdown adapters、Query Keys、filters 和 keyset pagination。
- [x] 按 task kind 保留完整 Domain Model，不压平成丢字段的通用模型。
- [x] 实现结构化 status 驱动的 controls；禁止解析自然语言 message 决定按钮。
- [x] Initial React 确认只使用 `/{id}/confirm/stream`。
- [x] 确认流复用公共 SSE envelope/transport，业务 event 使用独立 TaskPlan union/reducer。
- [x] 同一 deliberate action 保留 Idempotency-Key；`409` 和流终止后 refetch detail/list。
- [x] 区分浏览器 abort 与服务端 cancel，禁止自动重放真实工具操作。
- [x] 增加 list cursor、两种 task kind、幂等、409、confirm stream、abort/recovery、ownership 404 测试。
- [x] 完成 Slice Gate；执行 TaskPlan manual smoke；创建独立 Git checkpoint。

### Slice 7 - Knowledge Documents

Status: COMPLETED

Goal: 完成公共/部门/grant 范围内的文档列表、详情、预览、来源跳转和受保护下载。

- [x] 读取 Knowledge Documents spec，复核 Route/Schema/OpenAPI/CORS/runtime tests。
- [x] 实现 list/detail/content/download adapters、Query Keys、filters 和 keyset pagination。
- [x] 正确呈现 public 公共区域与非 public 部门语义，不在浏览器计算 ACL。
- [x] 按 render mode 安全展示 Markdown/plain/extracted text，并显示 truncation/warnings。
- [x] 实现 authenticated Blob download、`X-Source-Revision` 三方一致性校验和安全 `Content-Disposition` 文件名。
- [x] revision 不一致时丢弃 Blob、refetch detail/content；object URL 使用后立即 revoke。
- [x] 实现聊天 `doc_id` 来源站内跳转和隐藏式 404 体验。
- [x] 增加 public/department/grant UI 状态、revision mismatch、Blob URL cleanup、header filename、404 和安全渲染测试。
- [x] 完成 Slice Gate；执行 Documents manual smoke；创建独立 Git checkpoint。

### Slice 8 - User Access Management

Status: COMPLETED

Goal: 完成管理员和部门主管范围内的用户列表、详情、创建、完整 access 替换、状态修改和密码重置。

- [x] 读取 User Access Management spec，复核 catalog/user Route/Schema/OpenAPI/runtime tests。
- [x] 实现 server-trimmed catalog、用户 list/detail adapters、filters、cursor 和 Query Keys。
- [x] 从 catalog 构建账号、部门、角色、权限选项；禁止硬编码或任意 code 输入。
- [x] 实现创建与完整 access PUT snapshot、唯一主部门校验和 catalog drift 处理。
- [x] 实现禁用、重置密码、账号类型变更的确认和 pending lock。
- [x] 密码仅存在表单局部状态并在提交后清空；destructive mutations 不做乐观更新。
- [x] 当前用户身份/能力受影响时调用 AuthProvider reload；其他用户只失效业务 Query。
- [x] 增加 admin/manager/employee scope、422、403/404、409、自操作保护、credential revocation summary 测试。
- [x] 完成 Slice Gate；执行 User Management manual smoke；创建独立 Git checkpoint。

### Slice 9 - Cross-Department Document Grants

Status: IN_PROGRESS

Goal: 完成非 public 文档的精确跨部门只读授权、列表、审计展示和幂等撤销。

- [x] 读取 Document Grants spec，复核 Route/Schema/OpenAPI/runtime tests。
- [x] 实现 grant list/create/revoke adapters、filters、cursor 和 Query Keys。
- [ ] 创建流程只接受精确 target account 和 1–100 个非 public document IDs。
- [ ] 不建立未批准的跨部门用户目录，不为 public/同部门文档创建冗余 grant。
- [ ] 展示 created/existing counts、active/revoked audit facts 和安全错误。
- [x] 创建/撤销不做乐观更新，并失效 grants 与相关 documents Query。
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

- 9 - Cross-Department Document Grants

Context Recovery and Slice 9 Contract Reconnaissance Evidence (verified 2026-08-31 after usage-limit interruption):

- 用户于 2026-09-01 明确批准 CG010 Recommended Backend Change。授权只覆盖三条 Initial React Grant Route 的安全 request/business 422 projection、OpenAPI schema、runtime/OpenAPI/no-sensitive/top-level-field/form-level/non-Grant regressions与必要 service exception metadata；不改变 grant authorization、manager scope、target/document resolution、public/同部门/ACL redundancy policy、transaction、idempotency、conflict/403/404、audit、revoke、retrieval 或其他 Route。
- 授权后实施恢复确认 HEAD 为恢复/CG010 blocker checkpoint `2078587`，branch 为 `master...origin/master [ahead 88]`，staged diff 为空；Grant backend Route/Schema/service/exception handler/error schema/test scoped diff为空。外部 RAG Eval working set仍为 9 tracked + 23 untracked并继续隔离；恢复后的唯一 Next Action 是公共 HTTP/OpenAPI seam expected-red，不重做 Slice 8 或提前创建 Grant frontend code。
- 2026-09-01 再次从 Git 续接：HEAD 仍为 `35ecb2f`、branch 仍为 `master...origin/master [ahead 87]`；上一轮 `git add/commit` 因额度限制在进程创建前被拒绝，staged diff 仍为空。frontend 唯一 scoped diff 是本计划的恢复/CG010 记录，Grant backend scoped diff仍为空；因此未丢失、未误提交，也没有新的 implementation 进度可采信。
- frontend 与 backend 仍共享 Git root `D:/AI_Agent_Project`；confirmed HEAD 为 Slice 8 completion checkpoint `35ecb2f`，branch 为 `master...origin/master [ahead 87]`，staged diff 为空。Slice 8 data `6eeb740`、read-only UI `cabfd97`、mutation seam `54ea938`、draft policy `5df8950`、create `2b2a998`、access editor `2ddd1ed`、account controls `395d988`、identity reload `43defeb`、scope recovery `5c7f792` 与 role matrix `c1e037b` 均为 HEAD ancestors，对应源码真实存在；最后 verified completed Slice 为 8，未重新实现任何已通过 Gate 的 Slice。
- frontend scoped worktree 在侦察前为 clean，package、lockfile、OpenAPI snapshot、generated transport types 与 `src` 无差异；`pnpm contracts:check` 通过。当前 generated contract 的 Grant GET/POST/DELETE 三条 operation 仍全部把 `422` 声明为 `HTTPValidationError`。
- backend scoped worktree 仍只有 9 个 tracked RAG Eval modifications 与 23 个 untracked RAG Eval/dataset/report/runtime entries；完整 status、Grant scoped diff 与 staged diff 已检查，Grant Route/Schema/service/handler/error schema/test 均无未提交变化。该外部 working set 未读取内容、未修改、未暂存，也不归属 Slice 9。
- 已完整读取 Cross-Department Document Grants feature spec，并核对相关 SPEC/Architecture、backend `document_access_routes.py`、`document_access_schema.py`、service、repository、exception handler/error schema 与 `test_document_access_grants.py`。当前三条真实 Route 均未声明安全公共 422 response，global validation allowlist 也不包含 Grant Route。
- 无敏感 TestClient probe 对 invalid list `limit`、duplicate create `document_ids` 与超长 revoke path 均得到 `422`；runtime keys 只有 `code/error_category/message/request_id/trace_id`，没有 OpenAPI `HTTPValidationError.detail`，也没有 Feature/SPEC 所需的 `field_errors`。三条 runtime OpenAPI ref 均实际为 `#/components/schemas/HTTPValidationError`。
- 受控 create business-validation probe 得到 `DOCUMENT_ACCESS_GRANT_INVALID / 422`、同样没有 `field_errors`，并确认 service message marker 被原样公开。真实 service 的冗余授权分支把提交的 document IDs 拼接进该 message，因此当前公开响应存在 document ID echo；cursor invalid 则复用同一异常但应保持安全 form-level 语义。
- backend `test_document_access_grants.py`、`test_schema_field_descriptions.py` 与 `test_knowledge_document_read.py` 使用 repository `.venv` + `PYTHONPATH=src` 全部通过；前者覆盖部门范围、幂等、撤销、即时读取与基础 HTTP status/OpenAPI path，但只断言 duplicate body 为 422，不断言 Runtime/OpenAPI shape、field mapping、business no-echo 或公共 response schema，因此 green baseline 不能关闭该 gap。
- Repository/Git/Tests 证明原 Current Step、Next Action、KI006 inventory 状态与 Slice 9 `IN_PROGRESS` 已过期。现已提升为 CG010 并把 Slice 9 标记 `BLOCKED`；恢复后的唯一 Next Action 是等待用户批准或拒绝严格受限 fix，批准前不修改 backend 或创建 Grant frontend working set。

CG010 Completion Evidence (verified 2026-09-01):

- 独立 `test_document_access_grant_validation_contract.py` 按 public FastAPI Route + global handler seam 分步取得 expected-red：POST request runtime 缺少 `field_errors`；business exception 不接受 field metadata并返回 500；真实冗余授权 service 分支没有稳定 field；GET/DELETE runtime 缺少安全 projection；OpenAPI 没有 request/business discriminator。每个 tracer bullet 均以最小实现转绿。
- request 422 只投影 list query 的 `target_account/doc_id/status/department_code/limit` 与 create body 的 `target_account/document_ids`；malformed、unknown body、cursor、revoke path和无关 Route均保持 form-level或原有 shape。提交值、数组位置、raw Pydantic input/ctx/msg 与测试 marker不进入 HTTP body。
- `DocumentAccessGrantInvalidError` 运行时只允许 `document_ids/invalid` 或无 field；冗余授权 service 分支显式提供该 metadata，内部 exception message不再拼接 document IDs。GET invalid cursor返回固定安全 message与空 `field_errors`；Grant handler日志也使用固定 public message。
- GET/POST OpenAPI 422 为按 `code` 判别的 `RequestValidationErrorResponse | DocumentAccessGrantInvalidErrorResponse`，DELETE 422 只为安全 request response。当前 app 相对旧 snapshot仍为 58 paths，schemas 从 138 增至 140；仅 `/admin/document-access/grants` 与 `/{grant_id}` 两个 path item及 `RequestValidationFieldError`、两个新 Grant schema改变。
- backend focused green：新 CG010 contract、真实 `test_document_access_grants.py`、`test_knowledge_document_read.py`、schema descriptions，以及 Auth/Conversation/Chat/TaskPlan/User Administration/Knowledge Documents validation contracts；相关 `py_compile` 通过。原 authorization、manager scope、public/department/ACL policy、transaction、idempotency、403/404/409、audit、revoke与retrieval regressions未回退。
- 独立 backend checkpoint `068e336` 只包含 11 个 CG010 source/test 文件；frontend sync checkpoint `967ba14` 只包含 OpenAPI snapshot与 generated TypeScript。`pnpm contracts:generate`、`pnpm contracts:check` 与完整 `pnpm check` 通过：lint、typecheck、32 files / 172 tests、production build全部成功，仅保留既有约 531.05 kB 非阻塞 chunk warning；package/lockfile未变化。
- 实施期间并发 RAG Eval 工作流自行创建 `02b0f27`、`ac48164`、`51303cf`；路径核对确认不与 Grant/frontend contract重叠，也未混入 `068e336` 或 `967ba14`。当前仅剩两个外部 runtime TaskPlan 文件未跟踪并继续排除。CG010 关闭，唯一 Next Action推进为 Grant data/query seam expected-red。

Latest Context Recovery Evidence (verified 2026-08-31 before CG009 implementation):

- frontend 与 backend 目录仍共享 Git root `D:/AI_Agent_Project`，共同 confirmed HEAD 为 `01e2bc07cf3e1ad9cea0e5979911a882e593f231`，branch 为 `master...origin/master [ahead 61]`；全部 Slice 0-7 checkpoints、CG008 backend `0676928`、frontend sync `8072b65` 与 Slice 8 blocker checkpoint `01e2bc0` 都是当前 HEAD ancestor。staged diff 为空。
- frontend scoped worktree 只有本 Execution Plan 的既有恢复修改；package、lockfile、OpenAPI snapshot、generated types 与 `src` 无未提交差异。frontend 仍不存在 `src/features/user-management/`，`/admin/users` 与 `/admin/users/:userId` 仍只是 capability-gated placeholder，证明 Slice 8 business coding 尚未开始且已通过 Slice 不需要重做。
- backend scoped worktree 仍有 9 个 tracked RAG Eval modifications 与 23 个 untracked RAG Eval/dataset/report/runtime status entries；tracked diff、name/status 与 stat 已检查，未触及 CG009 的 User Administration Route/Schema/service/exception handler/error schema/tests。它们继续被明确排除，不修改、不暂存、不归入 CG009 checkpoint。
- current package graph 实际解析 pnpm `10.32.1`、`openapi-typescript@7.13.0`、TypeScript `6.0.3`、Vite `8.2.2` 与 Vitest `4.1.11`。frontend snapshot 与当前 `app.openapi()` canonical equality 为 true，均为 OpenAPI `3.1.0` / 58 paths / 136 schemas；七条 User Access operation 的 422 仍全部引用 `HTTPValidationError`。
- frontend `pnpm check` 实际通过 generated drift、Oxlint `--deny-warnings`、TypeScript、27 files / 134 tests 与 Vite production build（380 modules transformed）；仅保留既有约 505.44 kB 非阻塞 chunk-size warning。
- backend `test_user_administration_read.py` 与 `test_user_administration_write.py` 实际通过。真实 FastAPI Route + global handler probe 再次确认 request validation 422 只有五个通用字段且没有 `field_errors`；create/access 的受控 `ManagedUserAccessInvalidError` 同样没有 `field_errors`，并会把 service message 原样公开，marker probe 为 `marker_echo=True`。这进一步证明 CG009 必须使用固定安全 public projection，不能暴露或解析自然语言 message。
- Repository/Git/Tests 与计划记录的 Current Slice 一致；用户于 2026-08-31 明确批准 CG009 Recommended Backend Change。恢复后的唯一 Next Action 是新增独立 public HTTP contract test 并取得 expected-red；frontend User Access DTO/page 仍必须等 CG009 Runtime = OpenAPI = Tests、独立 backend checkpoint 与 contract sync 后才能开始。

CG009 Completion Evidence (verified 2026-08-31):

- `test_user_administration_validation_contract.py` 先在旧 `/admin/users` request runtime 缺少 `field_errors` 时 expected-red，再通过真实 FastAPI Route + global handler 转为 green；覆盖七条 operation 的 request 422、create/access discriminated business 422、固定安全 message、nested `department_access` 顶层折叠、path/malformed/unknown form-level fallback 与非 Admin Route 不扩展。
- `ManagedUserAccessInvalidError` 只接受 `username/account_type/department_access/direct_permission_codes` 与稳定 `invalid` code；User Administration service 的确定性公开分支显式提供 field/code，handler 不解析自然语言 message。事务、actor scope、catalog、冲突/404/self/last-admin、密码强度与 credential revocation 未改变。
- backend shared Auth/Conversation/Chat/Knowledge Documents/TaskPlan validation contracts、User Administration read/write database regressions、schema field-description regression与 relevant `py_compile` 全部通过。OpenAPI 相对旧 snapshot 只改变 6 个 User Administration path / 7 个 operation；仍为 58 paths，schemas 从 136 增至 138。
- 独立 backend checkpoint `9952c69` 只包含 10 个 CG009 contract/test 文件；外部 RAG Eval working set 未暂存、未提交。frontend snapshot/generated sync checkpoint `c6f1645` 只包含两个 generated artifacts，package/lockfile 未变化。
- `pnpm contracts:generate` 与 `pnpm contracts:check` 通过；generated create/access 422 为 `RequestValidationErrorResponse | ManagedUserAccessInvalidErrorResponse`。首次 `pnpm check` 在既有 Conversations create navigation test 出现一次时序失败，随后该文件 focused 11/11 通过，第二次完整 `pnpm check` 通过 contract drift、lint、typecheck、27 files / 134 tests 与 production build；既有 505.44 kB chunk warning 仍非阻塞。
- CG009 已达到 Runtime = OpenAPI = generated types = Tests 并关闭。Slice 8 frontend business implementation 获准开始；恢复后的唯一 Next Action 是先建立 User Management data/query seam expected-red，不直接跳到页面或 mutation UI。

Slice 8 Data Seam Evidence (verified 2026-08-31):

- `user-management-data.test.ts` 先因 `user-management-api` 等 production modules 不存在 expected-red；最小实现随后建立 generated catalog/list/detail DTO aliases、显式 allowlisted DTO-to-Domain mapping、opaque cursor merge、URL filter encoding 与 user-bound catalog/list/detail Query Keys。
- catalog 完全来自 server-trimmed response；adapter 不硬编码部门、账号类型、角色或权限 code，也不把 arbitrary scope/ACL 字段带入 Domain Model。list 只提交批准的 `query/status/department_code/cursor/limit`，detail user ID 经过 URL encoding。
- focused 6/6、typecheck、lint 与完整 `pnpm check` 通过：contract drift、lint、typecheck、28 files / 140 tests 与 production build 全部成功；package、lockfile和 generated contract 未变化，既有 505.44 kB chunk warning 仍非阻塞。
- frontend checkpoint `6eeb740` 只包含 `src/features/user-management/` 的 5 个 data/query files。唯一 Next Action 是为 read-only workspace 与真实 App route composition 建立 expected-red；不提前实现 mutation 表单。

Prior Context Recovery Evidence (verified 2026-08-30 after session change):

- frontend 与 backend 目录实际共享 Git root `D:/AI_Agent_Project`，共同 confirmed HEAD 为 `01e2bc07cf3e1ad9cea0e5979911a882e593f231`，branch 为 `master...origin/master [ahead 61]`。恢复检查开始时 frontend scoped worktree clean；整个 monorepo staged diff 为空。完成恢复校正后，frontend scoped worktree 只包含本 Execution Plan 的未暂存修改。
- backend scoped worktree 有 9 个 tracked RAG Eval modifications 与 23 个 untracked RAG Eval/dataset/report/runtime status entries；完整 tracked unstaged diff 已读取，未触及 User Administration Route/Schema/service/validation handler、frontend 或 committed OpenAPI contract。本恢复未修改、暂存或归属这些外部文件。
- Slice 0-7 记录的 checkpoint chain 均是当前 HEAD ancestor，`7cdbcaa..HEAD` 未发现 Revert commit；Git checkpoints 与源码一致。Slice 7 data `45873a3`、read-only UI `248378c`、download/revision `42af700` 均存在；`42af700..HEAD` 的 frontend `src`、package、lockfile 和 OpenAPI snapshot 无变化。CG008 backend `0676928` 与 frontend contract sync `8072b65` 仍存在，相关 backend files 在 `0676928..HEAD` 无 committed drift。
- 当前 frontend 仍没有 `src/features/user-management/` 或 User Management page implementation；`/admin/users` 与 `/admin/users/:userId` 只装配 capability-gated placeholder。Slice 8 进入 checkpoint `a66916c` 后，frontend business source、User Administration backend contract source、package、lockfile 与 OpenAPI snapshot均无 committed变化。
- package/lockfile 实际解析 pnpm `10.32.1`、`openapi-typescript@7.13.0`、TypeScript `6.0.3`、Vite `8.2.2`、Vitest `4.1.11`、`react-markdown@10.1.0` 与 `remark-gfm@4.0.1`。committed snapshot 与当前 `app.openapi()` canonical equality 为 true，均为 OpenAPI `3.1.0` / 58 paths / 136 schemas；七条 User Access operation 的 422 都仍引用 `HTTPValidationError`，generated contract drift check 通过。
- frontend recovery focused baseline 为 Documents/App 4 files / 30 tests 全部通过。完整 `pnpm check` 通过 generated drift、Oxlint `--deny-warnings`、TypeScript、27 files / 134 tests 与 Vite production build（380 modules transformed）；仅有约 505.44 kB 的既有非阻塞 chunk-size warning。
- backend User Administration read/write scripts、Knowledge Documents validation/HTTP/CORS contracts 与 schema field-description regression 全部通过。独立真实 Route + global handler probe 再次确认 list/path/create/access/status/reset-password request validation 422 只有 `code/error_category/message/request_id/trace_id`；受控 create/access `ManagedUserAccessInvalidError` 也只有同五项和 `MANAGED_USER_ACCESS_INVALID`，都没有 `field_errors`。
- Repository/Git/Tests 与本计划主状态一致；过期的 Slice 8 reconnaissance checkbox、Current Working Set Relevant Files、KI001 current-stage 文案和 KI006 current-snapshot 文案已修正。`docs/DEVELOPMENT.md` 的“19 files / 82 tests”及“文档、TaskPlan reducer 未实现”属于陈旧历史快照，但该文件明确声明 active Execution Plan 是实施进度权威；本 Recovery 不扩大范围修改该工具链文档。
- 恢复后的唯一 Next Action 仍是等待用户批准或拒绝 CG009 的严格受限 backend contract fix；批准前不修改 backend、不生成 User Access frontend DTO 或页面实现。

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
- Slice 6 已由 data `758929d`、read-only UI `ab8f2d9`、control policy `c24e9e5`、cancel/retry `875a0a8`、public event/reducer `9bb23c2` 与最终 confirm-stream/recovery implementation checkpoint `76a6875` 共同完成；最终 `pnpm check` 为 24 files / 111 tests，三个 backend TaskPlan contract tests、1280px/360px manual browser smoke 与 scoped diff review 均通过。
- Slice 7 已由 data `45873a3`、read-only UI `248378c` 与 download/revision `42af700` 三个 frontend checkpoints 完成；最终 `pnpm check` 为 27 files / 134 tests，backend Knowledge Documents validation/read/CORS contracts、1280px/360px manual browser smoke 与闪退后 focused recovery 均通过。

Currently Working On:

- Slice 9 / IN_PROGRESS。最后 verified completed Slice 为 8；Slice 8 全部 checkpoints、automated Gate 和 manual smoke 已完成且未重做。CG010已关闭，Grant data/query seam `e824fc3`与read-only workspace `8dea121`已持久化；CG011由backend `ea6df62`与frontend sync `03170c7`关闭，create draft/Dialog与revoke UI仍未创建。

Next Action:

- 在既有Document Grants data focused test中新增grantable-document transport/domain/query expected-red，只固定新GET、safe fields、filters、opaque cursor与user-bound query key。

CG011 Frontend Contract Sync Evidence (verified 2026-09-01):

- 从backend checkpoint `ea6df62`导出的snapshot与当前`app.openapi()` canonical equality为true，均为OpenAPI `3.1.0` / 59 paths / 142 schemas；diff只新增批准的grantable-document GET、两个safe response schemas与对应operation。
- `pnpm contracts:generate`与`pnpm contracts:check`通过；generated transport明确返回五个safe item fields、opaque `next_cursor`与request/business 422 union。package、lockfile与dependency graph无变化。
- frontend Grant/Knowledge Documents focused为6 files / 40 tests；完整`pnpm check`通过contract drift、lint、typecheck、35 files / 190 tests与production build，只保留既有约536.08 kB非阻塞chunk warning。
- 独立frontend checkpoint `03170c7`只包含OpenAPI snapshot与generated types；外部RAG Eval/runtime产物未读取、修改或暂存。CG011达到Runtime = OpenAPI = generated types = Tests，现已关闭。
- 关闭后完整文档复核发现SPEC endpoint清单、Architecture Grants映射、Feature contract表与Development snapshot证据仍停留在CG011前；checkpoint `758e9a6`只把四处记录对齐已批准runtime contract，没有新增产品行为。

CG011 Backend Fix Evidence (verified 2026-09-01):

- 独立backend checkpoint `ea6df62`新增唯一只读`GET /admin/document-access/grantable-documents`；response只含`doc_id/title/repository_path/document_department_code/document_type/next_cursor`，没有ACL、allowed users、raw visibility、source配置或permission集合。
- 真实database-backed service/repository test覆盖admin全范围与部门筛选、manager固定主管部门且不能扩大、employee拒绝、active source/document与public排除、escaped text filter、opaque keyset cursor；create/revoke语义、Knowledge Documents read policy与RAG/Agent/legacy stream均未修改。
- 公共FastAPI runtime/OpenAPI test覆盖query参数、safe 200 shape、allowlisted request 422、非法cursor稳定business 422与敏感marker不回显；schema field descriptions与py_compile通过。
- `test_document_access_grantable_documents.py`、`test_document_access_grants.py`、`test_knowledge_document_read.py`、`test_document_access_grant_validation_contract.py`及Auth/Conversation/RAG Chat/TaskPlan/Knowledge Documents/User Administration validation contract regressions全部通过。两个外部RAG Eval report目录与两个runtime TaskPlan文件未读取、修改或暂存。

CG011 Approval Recovery Evidence (verified 2026-09-01):

- 用户明确批准 CG011 Recommended Backend Change。授权只覆盖推荐的只读 grantable-document catalog、必要safe schema/Route/service/repository、actor scope与public exclusion、cursor/filter、安全validation/OpenAPI/tests；不新增用户搜索，不修改create/revoke业务语义、Knowledge Documents read policy、RAG/Agent/legacy stream或frontend create UI。
- 续接确认共享HEAD为 `dab4574`，branch为 `master...origin/master [ahead 5]`，tracked unstaged/staged diff均为空；仅有两个外部RAG Eval report目录和两个runtime TaskPlan文件未跟踪并继续排除。Grant data `e824fc3`、read-only workspace `8dea121`和CG011 blocker `dab4574`均为HEAD ancestors，已通过Slice不重做。
- 预先确认的TDD seam为公共FastAPI GET/OpenAPI/安全422，以及使用真实测试数据库的`DocumentAccessService`可观察行为；database是边界，不mock自有service/repository。唯一Next Action从Route不存在的HTTP expected-red开始，frontend contract生成和业务UI均后置。

Slice 9 Create Selection Contract Evidence (verified 2026-09-01):

- Feature要求创建流程从知识文档中选择一到多篇 non-public文档；主管的可选项必须受自己主管部门范围限制，管理员可按部门筛选。当前 Grant Route只有 list/create/revoke records，没有用于创建选择的 server-trimmed document catalog。
- frontend generated `KnowledgeDocumentItem`只有 `access_source/department_code/doc_id/...`，没有 `visibility`或 backend grant-management eligibility；单文档 detail虽有 raw `visibility`，仍没有 actor是否可管理该文档的服务端裁决。
- backend `DocumentAccessPolicy.resolve_access_source_from_scope()`先判断 `can_read_all`并返回 `admin`，再判断 public；真实 `test_knowledge_document_read.py`断言管理员页面的所有文档均为 `access_source=admin`。因此管理员所见 public文档无法从 list item的 `access_source`可靠排除。
- 同一 read policy允许 department、original ACL和explicit grant；主管因此可能读取并列出自己非主管部门的外部文档，而 `DocumentAccessService.create_grants()`另外强制所有文档必须等于主管 primary department。Knowledge Documents list是read scope，不是grant-management scope；逐项 detail只补 visibility，仍不能提供该管理裁决。
- backend源码/Route/OpenAPI搜索未发现 grantable-document catalog。当前 `get_grantable_documents(doc_ids)`只在create提交后按ID读取active记录，再由service执行scope/public/target-redundancy裁决，不提供可分页的安全选择列表。
- backend `.venv` + `PYTHONPATH=src` 下 `test_knowledge_document_read.py`与 `test_document_access_grants.py`均输出 passed，证明现有read/create授权行为未回退，但这些green tests不提供缺失的selection contract。共享worktree新增的两个RAG Eval report目录与两个runtime TaskPlan文件均视为外部产物，未读取内容、修改或暂存。
- Repository/Backend/Tests证明计划原 create draft Next Action不可安全执行，现已提升为 CG011并停止受影响编码。直接允许任意doc ID、用当前用户部门比较、把 `access_source`当visibility，或逐项detail后推断manager scope都会违反批准的Feature/Architecture与backend-authoritative authorization边界。

Slice 9 Read-only Workspace Evidence (verified 2026-09-01):

- 真实 App/AuthProvider/Router/QueryClient/MSW test先在 capability-gated `/admin/document-grants` placeholder 上取得 expected-red：Route region存在但不会请求 Grant GET，也没有授权列表。最小 Page/workspace composition转绿后，批准的导航与 CapabilityGuard保持不变。
- 四个列表筛选 `target_account/doc_id/status/department_code` 由 URL search params拥有；invalid status只作为无筛选处理，不向后端发明值。列表使用既有 user-bound infinite query、opaque cursor与稳定 merge；active/revoked卡片展示 repository path、doc ID、文档部门、目标账号及授权/撤销 actor和时间。
- loading、empty、field error与form/server error使用共享 PageState/TextField。`target_account/doc_id/status/department_code` 只显示 backend安全 field message；非字段错误只显示固定“文档授权列表加载失败”、safe code/request ID，不渲染 backend top-level raw message。
- focused最终为 Grant data/mutations/workspace、Knowledge Documents data与真实 App 5 files / 31 tests；`pnpm typecheck`、`pnpm lint`、`pnpm contracts:check`和 `git diff --check`全部通过。production scope search未发现新 browser storage、console、raw HTML、permission/ACL计算或额外 Route；package、lockfile、OpenAPI/generated contract均未变化。
- 独立 frontend checkpoint `8dea121` 只包含 Grant workspace/style/test、Page与 App composition/test共 6 个文件，不包含 create/revoke控件。唯一 Next Action已推进为 create draft/selection policy expected-red。

Slice 9 Data/Query Evidence (verified 2026-09-01):

- 按 TDD 依次取得并观察 query module缺失、domain model缺失、HTTP adapter缺失、create method缺失、revoke method缺失、create mutation缺失、revoke mutation缺失及 `403/404/409` 后未刷新记录的 expected-red；每个行为均以最小 production seam 转绿。
- generated aliases只引用 `CreateDocumentAccessGrantsRequest/Response`、`DocumentAccessGrantItem/ListResponse/User`；adapter显式映射批准的 grant、grantee和审计字段，测试中的 `private_acl/private_scope` 不进入 Domain Model。GET 只发送非空 `target_account/doc_id/status/department_code/cursor` 与固定 limit，cursor保持不透明；grant ID只用于 `encodeURIComponent` 后的批准 DELETE Route。
- Query Keys以当前认证用户为首个 boundary并包含完整 URL filters；infinite query使用服务端 opaque cursor，page merge保持服务端顺序并按 `grantId`保留首次出现。前端没有缓存允许读取的 document ID 集合，也没有计算授权范围。
- create/revoke hooks不做 optimistic cache写入。成功后只失效当前用户的 grant list、knowledge document list及响应实际涉及 doc IDs 的 detail/content；无关文档 detail保持有效。`403/404/409` 只重新加载 grant records，不根据不可见原因作推断。
- focused最终为 Document Grants data/mutations与 Knowledge Documents data 3 files / 20 tests；`pnpm typecheck`、`pnpm lint`、`pnpm contracts:check`和 `git diff --check`均通过。package、lockfile、OpenAPI snapshot与 generated types未变化；两个外部 runtime TaskPlan文件继续保留且未读取、修改或暂存。
- 独立 frontend checkpoint `e824fc3` 只包含 `src/features/document-grants/` 的 6 个 data/query source/test文件。共享仓库在 checkpoint前已由另一会话把 CG010与 RAG Eval提交推送至远端 `6a6a61b`；本轮核对后无需 pull，未重做任何已通过 Slice。唯一 Next Action已推进为 read-only workspace/App expected-red。

Slice 8 Final Manual Smoke and Completion Evidence (verified 2026-08-31):

- manual smoke 使用只监听 `127.0.0.1` 的临时虚构 Auth/User Administration service 与实际 Vite app；1280px 完成登录、list、opaque cursor 加载、URL query filter、catalog-backed create并导航详情。创建 Dialog 的账号/部门/角色/直接权限均来自服务端 catalog。
- detail smoke 完成 access 完整 PUT：账号类型变化第一次保存不发最终 mutation，明确出现“确认账号类型变更并保存”后才成功；随后禁用确认与 reset-password 均成功，页面分别只显示撤销 `refresh token/API Key` 数量，没有凭证内容。
- `LAST_ADMIN_CONFLICT / 409` 保留目标详情、显示固定“保存访问失败”与 safe code，临时 raw marker 未渲染；hidden target reset `404` 精确 replace navigate 到 `/admin/users`、Dialog 已卸载且 raw marker 未渲染。
- 1280px list 的 body `clientWidth=scrollWidth=1280`，main 为 `1000=1000`。360px list/detail 的 body/main 均为 `clientWidth=scrollWidth=345`；create/access Dialog 均为 328px wide、left 8.5/right 336.5，完整位于 360px viewport 内且自身无横向 overflow。
- 移动端 access Dialog 视觉检查保持蓝白主调、字段分组与可见 primary action；Escape 关闭后焦点回到“编辑访问”，reset Dialog 关闭后焦点回到“重置密码”。browser console warning/error 为空。
- browser viewport override、tab、临时 Vite/backend services 和 smoke script均已清理。清理后 frontend scoped worktree/staged diff为空，package/lockfile/OpenAPI/generated artifacts无差异，`pnpm contracts:check` 再次通过；backend 外部 RAG Eval working set继续保持隔离。
- Slice 8 由 data `6eeb740`、read-only UI `cabfd97`、mutation seam `54ea938`、draft policy `5df8950`、create UI `2b2a998`、access editor `2ddd1ed`、account controls `395d988`、identity reload `43defeb`、scope recovery `5c7f792` 与 role matrix `c1e037b` 共同完成。最后 verified completed Slice 现为 8；唯一 Next Action 已推进为 Slice 9 contract reconnaissance。

Slice 8 Automated Final Matrix Evidence (verified 2026-08-31):

- 新增真实 department-manager AuthProvider 场景：`can_manage_users=true / own_department` 开放入口，但创建 Dialog 只展示 server-trimmed employee account type 与当前 catalog 部门；admin/department-manager 选项不存在，前端没有复制 actor scope 或构造任意 code。
- 既有 App tests 已固定 employee `can_manage_users=false` 时导航入口隐藏且 direct visit 安全返回 Chat；admin mutation suite覆盖创建、access/status/reset。与新增 manager test共同形成三类 actor discoverability/catalog matrix，实际授权仍由每次 backend request 裁决。
- focused role matrix 为 User Management mutation + App 2 files / 20 tests；完整 `pnpm check` 通过 contract drift、lint、typecheck、32 files / 172 tests 与 production build，仅保留约 531.05 kB 非阻塞 chunk warning。package、lockfile、OpenAPI snapshot与 generated types无差异。
- backend repository `.venv` + `PYTHONPATH=src` 下 `test_user_administration_validation_contract.py`、`test_user_administration_read.py`、`test_user_administration_write.py` 全部输出 passed；确认 CG009 Runtime/OpenAPI/no-sensitive contract、真实 read scope 和 write transaction/self/last-admin/credential behavior未回退。
- scoped endpoint/sensitive-data review只发现批准的 catalog、list/detail/create/access/status/reset-password routes；production 未使用任意外部 URL、console、browser storage、raw HTML 或凭证内容。checkpoint `c1e037b` 只增加 manager role test，backend 外部 RAG Eval working set仍未修改、未暂存。
- 唯一 Next Action 已推进为 User Management manual browser smoke；完成前 Slice 8 保持 IN_PROGRESS。

Slice 8 Mutation Scope-loss Evidence (verified 2026-08-31):

- access `403` 与 reset-password `404` App/Router/MSW tests 先证明当前实现会留在目标详情并继续显示 Dialog expected-red；同时发现路径断言最初使用子串匹配会把 `/admin/users/user-reader` 误判为列表，已收紧为精确 `^/admin/users$`，未改变产品期望。
- 最小实现把 mutation error 交回详情 route owner；只在 `ApiError.statusKind` 为 `authorization/not_found` 时 replace navigate 到 `/admin/users`。access/status/reset 共用该 route recovery，不把 409、422 或网络错误误判为 scope loss。
- 返回列表会卸载目标详情与 Dialog，密码 local state随组件销毁；403/404 raw backend message 均不渲染。409 仍保留详情并 refetch，422 仍保留表单并映射 allowlisted field，错误分支没有合并。
- focused mutation UI 为 1 file / 12 tests，User Management + App 为 6 files / 44 tests；lint/typecheck 与完整 `pnpm check` 通过，最终为 32 files / 171 tests 与 production build，仅保留约 531.05 kB 非阻塞 chunk warning。
- frontend checkpoint `5c7f792` 只包含 scope-loss route recovery 与 tests；package、lockfile、generated contract 和 backend 均未变化，外部 RAG Eval working set保持隔离。唯一 Next Action 已推进为最终角色/scope automated matrix。

Slice 8 Current-user Identity Reload Evidence (verified 2026-08-31):

- 真实 App/AuthProvider/Router/MSW test 先在当前用户 access mutation 成功后 `/auth/me` 与 `/auth/capabilities` 请求计数均未增长处 expected-red；最小 wiring 只把 AuthProvider 已有 `reloadIdentitySnapshot()` Interface 注入 User Management 页面，不复制 `/auth/me` 或 capabilities 到 TanStack Query。
- mutation 成功 callback 在 target `user_id === currentUser.userId` 时调用该 Interface，由 AuthProvider 继续负责并行读取、原子发布、generation stale rejection 与 transient failure 的旧完整快照保留；feature 不直接修改 current user 或 capabilities 任一对象。
- 同一 test file 的非当前用户 access 成功断言证明 me/capability 请求计数保持不变；其他用户仍只执行既有 detail/list Query reconciliation。callback 只在 access/status/reset 成功路径调用，422/409/403/404 不触发 identity reload。
- User Management + Auth + App focused 为 12 files / 67 tests；lint/typecheck 与完整 `pnpm check` 通过，最终为 32 files / 169 tests 与 production build，仅保留约 530.83 kB 非阻塞 chunk warning。
- frontend checkpoint `43defeb` 只包含 identity wiring 和测试；package、lockfile、generated contract 与 backend 均未变化，外部 RAG Eval working set保持隔离。唯一 Next Action 已推进为 mutation 403/404 scope-loss recovery expected-red。

Slice 8 Account Controls Evidence (verified 2026-08-31):

- `UserManagementMutations.test.tsx` 的 status/reset-password 4/4 expected-red 准确失败于详情页缺少“禁用账号”和“重置密码”入口；最小账号控制组件随后接入既有 status/reset mutation hooks，没有新增 endpoint 或复制 transport policy。
- 禁用使用显式确认 Dialog，只提交 `{status:"disabled"}`；reset 只提交 `{new_password}`。delayed response 测试证明提交期间确认按钮及密码字段锁定，detail 在成功 response 前不被乐观修改。
- password 只存在组件 local state，在成功关闭后重新打开为空，request/422 failure 后也立即清空；`new_password` 422 只显示 allowlisted field message，raw backend message 不渲染。status `409` 保留旧服务端状态、显示固定安全错误和 code/request ID，并重新拉取 detail/list。
- status/reset 成功只展示被撤销的 refresh token 与 API Key 数量，不展示任何凭证内容。focused mutation UI 为 1 file / 9 tests，全部 User Management 为 5 files / 34 tests；lint/typecheck 及完整 `pnpm check` 通过，最终为 32 files / 168 tests 与 production build，仅保留约 530.49 kB 非阻塞 chunk warning。
- frontend checkpoint `395d988` 只包含账号控制组件、详情 composition 与 mutation UI tests；package、lockfile、generated contract 和 backend 均未变化，外部 RAG Eval working set保持隔离。唯一 Next Action 已推进为 current-user AuthProvider reload expected-red。

Slice 8 Access Editor Evidence (verified 2026-08-31):

- `UserManagementMutations.test.tsx` 的 access editor 3/3 expected-red 准确失败于详情页缺少“编辑访问”入口；最小实现随后从 server detail 初始化 catalog-only draft，并通过既有纯 policy builder 提交完整 PUT snapshot，不发送有效权限、内部 scope 或任意 code。
- 账号类型变化第一次保存不会发请求，必须通过独立二次确认；mutation pending 时字段、普通保存与二次确认均锁定。成功 response 写入 detail cache并失效 list，页面只显示服务端返回的新账号类型。
- request/business `422` 只映射 `account_type/department_access/direct_permission_codes` allowlist，raw backend message 不渲染；`409` 显示固定安全消息、code/request ID，并沿用 query seam 重新拉取 detail/list，保留服务端事实且不做 optimistic write。
- focused mutation UI 为 1 file / 5 tests，全部 User Management 为 5 files / 30 tests；lint 与 typecheck 通过。完整 `pnpm check` 通过 generated drift、lint、typecheck、32 files / 164 tests 与 production build，仅保留约 527.20 kB 非阻塞 chunk-size warning。
- frontend checkpoint `2ddd1ed` 只包含 access dialog、详情入口/style 与 mutation UI tests；package、lockfile、generated contract 和 backend 均未变化，外部 RAG Eval working set保持隔离。唯一 Next Action 已推进为 status/reset-password controls expected-red。

Slice 8 Create UI and Gate Stabilization Evidence (verified 2026-08-31):

- `UserManagementMutations.test.tsx` 的创建流程先因页面没有“创建账号”入口 2/2 expected-red；最小 UI 随后用 server-trimmed catalog 渲染 account/department/role/direct-permission choices，构建完整 create snapshot，并在成功后导航到 URL-encoded detail。
- 创建密码仅存在 Dialog local state；pending 时表单与提交锁定，每次成功、HTTP failure 或本地 draft validation 后都清空。测试从成功详情返回列表并重新打开 Dialog，以及在 delayed 422 后检查 input，分别证明成功/失败清空；Query cache不保存密码。
- request/business `422` 只按批准 field allowlist 映射，raw backend message 不渲染；catalog drift 使用纯 reconciliation 派生最新 draft并要求显式确认，未通过确认不提交。非 field error 只显示固定安全消息、code 与 request ID。
- 恢复后 lint 首先捕获 render-time ref access；改为可渲染 state 后 focused 3 files / 16 tests、lint/typecheck green。完整 Gate 连续两次暴露既有 Conversations probe 非等待式异步断言；test-only checkpoint `e6dd779` 仅用 `waitFor` 等待相同 `/chat/session-new` 期望，不改 production behavior或断言值。
- Conversations focused 11/11 与随后两次完整 `pnpm check` 通过；最终 Gate 为 contract drift、lint、typecheck、32 files / 161 tests 与 production build。创建 UI checkpoint `2b2a998` 只包含 5 个 User Management UI/test files；package、lockfile、generated contract 与 backend 均未变化，外部 RAG Eval working set保持隔离。
- 唯一 Next Action 已推进为 detail access 完整 PUT 编辑器 expected-red；status/reset-password、current-user AuthProvider reload、最终 scope/409/credential summary matrix 与 manual smoke 尚未实现或宣称完成。

Context Recovery Evidence (verified 2026-08-31 after usage-limit interruption during Slice 8 create UI):

- frontend/backend 仍共享 Git root `D:/AI_Agent_Project`；共同 confirmed HEAD 为 plan checkpoint `0577228`，branch 为 `master...origin/master [ahead 73]`，staged diff 为空。最近 checkpoints `6eeb740`、`cabfd97`、`54ea938`、`5df8950` 及各自 plan checkpoints都真实存在；最后 verified completed Slice 仍为 7，Slice 8 最后已 checkpoint 的实施边界为 catalog-backed draft policy。
- frontend 当前未 checkpoint working set 仅为创建账号 UI：tracked `UserManagementWorkspace.tsx`/CSS，加上 untracked `CreateManagedUserDialog.tsx`、`ManagedUserAccessFields.tsx` 与 `UserManagementMutations.test.tsx`。完整 scoped source/diff 已读取；创建 App/Router/MSW test 的 2/2 expected-red 曾因“创建账号”入口不存在，当前恢复重跑与 read-only test 合计 2 files / 7 tests green。
- 当前创建实现只提供 server-trimmed catalog 选项、完整 create snapshot、safe 422 field mapping、pending lock、password finally clear、成功导航与 catalog drift reconfirmation；尚未 checkpoint，也不代表 detail access/status/reset-password、AuthProvider reload 或 Slice Gate 完成。
- `pnpm typecheck` 与 `pnpm contracts:check` 通过；package、lockfile、OpenAPI snapshot 与 generated types均无差异。`pnpm lint` 真实失败于 `CreateManagedUserDialog.tsx:84` 的 `react(refs)`：render 阶段读取 `confirmedCatalog.current`。当前唯一 Next Action 是用可渲染 state 表达该确认状态，不禁用规则、不改测试。
- backend 仍为 9 个 tracked RAG Eval modifications 与既有 untracked RAG Eval/dataset/report/runtime entries；它们不触及 User Administration contract，本恢复未修改、未暂存，也没有依据中断前口头状态重跑无关 backend tests。
- catalog confirmation 已从 render-time ref 改为可渲染 state；随后 lint、typecheck 与 User Management focused 3 files / 16 tests 全绿。完整 `pnpm check` 连续两次只在既有 `ConversationsWorkspace.test.tsx` 创建导航断言失败，而该文件单独 11/11 通过。断言当前使用 `findByLabelText('current-route')` 查找测试开始即存在的 probe，不能等待其文本异步变化；唯一 Next Action 因而修正为用 `waitFor` 保持相同最终路径期望，不改 Slice 4 production behavior。

Slice 8 Catalog-backed Draft Policy Evidence (verified 2026-08-31):

- `user-management-draft.test.ts` 先因 production module 不存在 expected-red；最小纯函数模块只建立 access draft、catalog reconciliation、提交前 validation 与 generated create/access DTO builder，不调用网络、不计算有效权限。
- catalog drift 会移除已撤销或重复的 department/role/direct-permission code、清空不再允许的 account type 并设置 `requiresReconfirmation=true`；未变化 draft 保持原样。提交 builder 独立拒绝任意 code 与重复项，要求且只允许一个主部门，防止绕过 UI 直接构造草稿。
- focused 1 file / 9 tests、typecheck 与 lint 通过。第一次完整 `pnpm check` 仅在既有 Conversations create navigation 时序断言失败；该文件 focused 11/11 通过后，完整重跑通过 contract drift、31 files / 159 tests 与 production build，未弱化断言。
- package、lockfile、generated contract 与 backend 均未变化；scoped diff/check 通过。frontend checkpoint `5df8950` 只包含 draft policy 与 test 两个文件，backend 外部 RAG Eval working set未修改、未暂存。
- 唯一 Next Action 已推进为 list-side 创建账号表单 App/Router/MSW expected-red；detail access/status/reset-password controls、确认 Dialog、AuthProvider reload 与 manual smoke 尚未实现或宣称完成。

Slice 8 Mutation Data Seam Evidence (verified 2026-08-31):

- `user-management-mutations.test.tsx` 先以 5/5 expected-red 证明 create/access/status/reset-password hooks 全部不存在；最小实现只扩展 generated request/response aliases、allowlisted response-to-domain mapping、四条 HTTP adapter 与 TanStack Query reconciliation，没有加入表单或页面控件。
- MSW 固定 `POST /admin/users`、encoded target `PUT .../access`、`PATCH .../status` 与 `POST .../reset-password` 的 method/path/body；create/access/status 成功用 server response 写入 detail 并失效 list，reset-password 因 response 不含 detail 而失效 detail/list。
- delayed status response 证明 pending 时旧 server snapshot 保持不变、没有 optimistic write；target mutation `409` 保留旧 snapshot 并失效 detail/list，create `409` 只失效 list。密码只作为 mutation argument 进入 request，不写入 Query cache，响应只保留撤销计数。
- focused expected-red/green 为 1 file / 5 tests；User Management + App 回归为 4 files / 23 tests。typecheck、lint 与完整 `pnpm check` 通过 contract drift、30 files / 150 tests 与 production build；package、lockfile、generated contract 与 backend 均未变化。
- scoped staged diff/check 通过，frontend checkpoint `54ea938` 只包含 5 个 User Management contract/model/API/query/test 文件；backend 外部 RAG Eval working set未修改、未暂存。唯一 Next Action 已推进为 catalog-backed access draft policy expected-red。

Slice 8 Read-only Workspace Evidence (verified 2026-08-31):

- `UserManagementWorkspace.test.tsx` 先因 public workspace module 不存在 expected-red；最小实现随后用真实 QueryClient/Router/MSW seam 接入 `/admin/users` 与 `/admin/users/:userId`，替换原 capability-gated placeholder，但不提前加入 mutation controls。
- list 从 URL 读取 `query/status/department_code`，使用 server-trimmed catalog 展示部门与账号类型、保留 opaque cursor 并追加页面；detail 只展示 server 返回的账号、部门、角色、直接权限与有效权限事实，不在浏览器计算授权。
- request `422` 只映射批准字段；`403/404` detail 统一为不可枚举的“用户不可用”，不渲染 backend raw message。focused workspace 5/5、workspace + App 12/12、typecheck、lint 与完整 `pnpm check` 全部通过；完整 Gate 为 29 files / 145 tests + production build。
- package、lockfile、OpenAPI snapshot 与 generated types 未变化；scoped staged diff review 和 `git diff --cached --check` 通过。frontend checkpoint `cabfd97` 只包含 App route composition、User Management page/workspace/style/test 六个文件；backend 外部 RAG Eval working set未修改、未暂存。
- 唯一 Next Action 已推进为四条 User Management mutation 的 typed transport/query reconciliation expected-red；创建/access/status/reset-password 表单、确认 Dialog、password lifecycle 与 AuthProvider reload 尚未实现或宣称完成。

Slice 8 Contract Reconnaissance Evidence (verified 2026-08-30):

- 进入 Slice 8 的 plan checkpoint 为 `a66916c`；Slice 7 已完成且没有重新实现。完整读取 User Access Management feature spec，并复核 SPEC 的 `can_manage_users` route/capability、catalog-only options 与通用 `422` 字段映射要求。
- backend `user_admin_routes.py` 与 `user_admin_schema.py` 确认 Initial React 使用 catalog、list/detail、create、完整 access PUT、status PATCH 与 reset-password 共 7 条 Route；请求模型禁止 extra，写入字段与列表 filters 都有明确 Pydantic constraints。
- 当前 frontend OpenAPI snapshot 中上述 7 条 Route 的 `422` 全部引用 `#/components/schemas/HTTPValidationError`。真实 Route + global handler + dependency override 的无敏感 TestClient probe 对 invalid list `limit/status`、invalid path、empty create/access、invalid status 与 empty reset-password 全部返回 422，但 runtime keys 只有 `code/error_category/message/request_id/trace_id`，没有 `detail` 或 `field_errors`。
- 进一步以受控 fake service 触发 `ManagedUserAccessInvalidError`，证明 create/access 的业务约束 422 runtime code 为 `MANAGED_USER_ACCESS_INVALID`，同样只有五个顶层公共字段，没有可判别 account/department/role/permission field。当前公共 validation allowlist 没有任何 Admin Route，generated contract 因而不能支持 feature 要求。
- backend `test_user_administration_read.py` 与 `test_user_administration_write.py` 均通过；后者只验证一个 extra status field 返回 422 status，不断言 runtime/OpenAPI schema equality 或业务 422 field mapping，因此成功 baseline 不能关闭 CG009。
- package、lockfile、OpenAPI snapshot 与 generated types 无未提交变化；共享 backend 外部 RAG Eval working set 保持隔离。唯一 Next Action 已修正为等待 CG009 严格受限授权，批准前停止受影响编码。

Slice 7 Contract Reconnaissance Evidence (verified 2026-08-30):

- confirmed HEAD 为 plan checkpoint `f276006`；进入 Slice 7 时 frontend worktree clean。共享 backend 外部 evaluation working set 在本次 reconnaissance 期间变为 8 个 tracked modifications 与 18 个 untracked status entries，本任务未读取其内容、未修改、未暂存。
- 完整读取 Knowledge Documents feature spec；当前 frontend 已有 Chat/Conversation 的安全 `doc_id -> /documents/{docId}` 站内来源链接，但没有 knowledge-documents feature 数据层、adapter、query 或 page implementation，未通过目录名推断完成度。
- backend 四条 approved Route、`KnowledgeDocumentItem/Detail/ContentResponse`、keyset list、public/department/explicit-grant access source、hidden 404 service policy、download `X-Source-Revision`/`Content-Disposition` 与 CORS expose headers 均存在；generated snapshot 也声明相同 download headers。
- backend `assert_http_contract()` 与 `assert_cors_contract()` focused baseline 通过；frontend Conversations source-link test 1 file / 11 tests、Chat/public-event source model 2 files / 16 tests 与 `pnpm contracts:check` 通过。
- 使用真实 Route + global exception handler + dependency overrides 的无敏感 TestClient probe 证明 list `limit=0`、invalid `document_type` 与 65 字符 path 均返回 422，runtime keys 只有 `code/error_category/message/request_id/trace_id`，marker 未回显；四条 Route 的 OpenAPI 422 却全部引用 `HTTPValidationError`。CG008 因而满足 Blocking Condition。

CG008 Closure Evidence (verified 2026-08-30):

- expected-red 公开 TestClient contract test 先因四条 Route runtime 缺少 `field_errors` 失败；最小 backend 修复只为 list query `query`、`department_code`、`document_type`、`limit` 建立 allowlisted projection，`cursor`、path `doc_id`、model/unknown error 保持 `field_errors=[]`，且不回显 validation input/ctx/raw msg 或文档敏感信息。
- 独立 backend checkpoint `0676928` 只包含四条 Knowledge Documents GET Route 的安全 422 response model、allowlist 和 runtime/OpenAPI/no-sensitive/form-level/non-allowlisted regression tests；ingestion/admin、compatibility、mutation、ACL、read/download 业务行为均未修改。
- backend Knowledge Documents/Auth/Conversation/RAG Chat/TaskPlan validation contract 与 Knowledge Documents HTTP/CORS regressions 全部通过；新 contract test 明确验证四条 Route 的 Runtime = OpenAPI = Tests。
- frontend OpenAPI snapshot 与 generated transport types 已从 backend `0676928` 重新导出并由独立 checkpoint `8072b65` 持久化；差异仅为四条 Route 的 422 引用及公共字段枚举新增 `department_code`、`document_type`，package/lockfile 未变化。
- `pnpm contracts:check` 通过。首次 `pnpm check` 在既有 Conversations 创建导航断言出现一次非稳定时序失败；同文件 focused 11/11 立即通过，完整重跑 `pnpm check` 通过 contract drift、lint、typecheck、24 files / 111 tests 与 production build。CG008 因而关闭，Slice 7 恢复。

Context Recovery Evidence (verified 2026-08-30 after quota interruption during Slice 7 data seam):

- frontend/backend 共享 branch 为 `master...origin/master [ahead 56]`，confirmed HEAD 为 plan checkpoint `426047b`，staged diff 为空。CG008 backend `0676928`、frontend contract sync `8072b65` 与 plan closure `426047b` 均真实存在；最后 verified completed Slice 仍为 6，没有重新实现已通过 Gate 的 Slice。
- frontend 唯一未 checkpoint 的本任务 working set 是 `src/features/knowledge-documents/` 下 5 个新文件；backend 另有外部 RAG Eval tracked/untracked working set，本任务未读取其内容、未修改或暂存。package、lockfile、OpenAPI snapshot 与 generated transport types均无未提交差异。
- Repository source 显示 generated DTO alias、DTO-to-domain allowlisted projection、四条 approved GET Route adapter、opaque cursor/non-empty filters、用户隔离 list/detail/content Query Keys 与 hooks 已存在。expected-red 曾准确因缺失 `knowledge-document-api` seam 失败；恢复后 focused test 1 file / 6 tests、`pnpm contracts:check` 与 typecheck 均通过。
- backend `test_knowledge_document_validation_contract.py` 与 Knowledge Documents `assert_http_contract()`/`assert_cors_contract()` 恢复重跑通过，确认当前 data seam 所依赖的 Runtime/OpenAPI contract 未回退。原 Current Step/Next Action 因而过期，唯一 Next Action 修正为完成该 data seam 的 scoped review 和独立 checkpoint。
- scoped lint、typecheck、focused 1 file / 6 tests、generated contract drift 与安全搜索通过；data seam 由 checkpoint `45873a3` 持久化，明确不包含 UI、revision 比对、object URL 或下载保存副作用。唯一 Next Action 随 checkpoint 推进为只读 UI expected-red。
- 只读 UI expected-red 先因缺少 `KnowledgeDocumentWorkspace` public seam 失败；最小实现接入真实 `/documents` 与 `/documents/:docId` route composition，URL filters/opaque pagination、access-source 说明、三种 render mode、allowlisted warning projection 和 hidden 404 后 focused 1 file / 6 tests 通过。
- scoped lint、typecheck 与 data/UI/App regression 3 files / 19 tests 通过；Markdown raw HTML/credential URL、未知 warning 和 backend raw error message 均未进入页面，详情 404 时 content Route 不发起请求。当前唯一 Next Action 是完成 scoped review/checkpoint，再进入 download revision TDD。
- scoped diff/security review 通过；只读 UI 由 checkpoint `248378c` 持久化，未包含下载保存、object URL 或 revision reconciliation。唯一 Next Action 已推进为 download policy expected-red。
- download policy expected-red 先因缺少 side-effect seam 失败；最小实现要求 detail/content revision 预先一致、下载 `X-Source-Revision` 再一致，并只接受安全 `attachment` 文件名。missing/unsafe filename 转为固定 protocol error；create object URL 后无论 save trigger 成败均在 `finally` revoke。
- policy tests 1 file / 8 tests 与页面 integration 1 file / 9 tests 通过；页面在 detail/content mismatch 时隐藏旧内容并 refetch 两个 Query，在下载头 mismatch 时丢弃 Blob、不创建 object URL并重新同步，成功时只显示解析后的安全文件名。
- scoped lint、typecheck 与 Documents/App/Conversation regressions 5 files / 41 tests 通过。当前唯一 Next Action 是完成 scoped review/checkpoint，再执行完整 Slice Gate 与 manual smoke。
- scoped diff/security review 通过；download/revision seam 由 checkpoint `42af700` 持久化，只调用批准的 authenticated download Route，不保留 response headers、partial Blob 或 object URL。唯一 Next Action 推进为完整 Slice Gate。

Slice 7 Final Gate and Crash Recovery Evidence (verified 2026-08-30):

- Codex app 闪退后重新从 Git/Repository/Tests 恢复：共享 branch 为 `master...origin/master [ahead 59]`，confirmed HEAD 为 `42af700`，staged diff 为空；Slice 7 的 data `45873a3`、read-only UI `248378c` 与 download/revision `42af700` checkpoints 均真实存在，package、lockfile、OpenAPI snapshot 与 generated transport types 无未提交差异。共享 backend 外部 RAG Eval working set 保持隔离，本任务未读取其内容、未修改或暂存。
- 完整 `pnpm check` 通过 generated contract drift、Oxlint `--deny-warnings`、TypeScript、27 files / 134 tests 与 Vite production build（380 modules transformed）。Vite 仅报告约 505.44 kB 的非阻塞 chunk-size warning；本 Slice 未因此引入未经批准的代码拆分或依赖变化。
- backend `test_knowledge_document_validation_contract.py` 与 Knowledge Documents `assert_http_contract()` / `assert_cors_contract()` 通过；闪退恢复后再次运行 `pnpm contracts:check`、Documents focused 3 files / 23 tests 以及同组三项 backend contracts，全部通过。
- 闪退后使用只监听 `127.0.0.1` 的虚构 Auth/Knowledge Documents service 重新执行 browser smoke：1280px 列表、URL filters、opaque cursor pagination、详情安全 Markdown、download revision mismatch、hidden 404 均通过；raw backend 404 message 和 raw HTML 未进入页面，`main` 内无 script element。
- 360px 列表与详情的 body/main `clientWidth=scrollWidth=345`，无横向溢出；browser console warning/error 为空。browser tab、viewport、临时 service、dev server 与 smoke script 均已清理。
- Repository/Git/Tests 与本计划比较后，过期的 Slice 7 Current Step、Next Action、Current Working Set 和未完成 Gate 已修正。Slice 7 现为 COMPLETED；恢复后的唯一 Next Action 是进入 Slice 8，只做 User Access feature/backend contract reconnaissance，未重做任何已通过 Gate 的 Slice。

Slice 6 Final Gate Evidence (verified 2026-08-30):

- focused TaskPlan tests：5 files / 26 tests 通过；覆盖唯一 confirm-stream Route、`confirmed:true`、request ID/Idempotency-Key、pre-stream 401 replay、409 refetch/no replay、protocol interruption、terminal/abort/recovery、route-boundary abort 和不可枚举 ownership 404。
- `pnpm check`：generated contract drift、Oxlint `--deny-warnings`、TypeScript、24 files / 111 tests 与 Vite production build 全部通过；373 modules transformed。package/lockfile/dependency graph 未变化，沿用同一 lockfile 下 Slice 5 的 `pnpm audit --audit-level high` 无已知漏洞证据。
- backend `test_agent_task_plan_stream_public_contract.py`、`test_agent_task_plan_validation_contract.py`、`test_agent_task_plan_resource_visibility_contract.py` 全部通过；确认 Runtime = OpenAPI = Tests、安全 public-event projection、422 form-level fallback、owned-resource 404 及 Initial React/non-stream confirm 范围边界仍成立。
- manual browser smoke 使用仅监听 `127.0.0.1` 的虚构 Auth/TaskPlan service：1280px 与 360px 页面布局通过，360px body/main `scrollWidth=360`；确认 Dialog 在两种 viewport 内完整可见，Escape 关闭后焦点回到“确认执行”。
- browser 网络记录只有 `/agent/task-plans/{id}/confirm/stream` POST，body 为 `{"confirmed":true}`，每个 action 均有 UUID request ID 与 Idempotency-Key；成功流显示结构化 timeline 并 refetch 为“已完成”，持续流在 route change 后 abort，新 TaskPlan 不继承旧 progress/停止接收按钮。console warning/error 为空。
- scoped `git diff --check -- .` 通过；endpoint/sensitive-output 搜索与完整 frontend diff 复核无非流式 `/confirm`、raw unknown payload、生产 token/password/ACL/internal URL、临时 smoke 文件或无关改动。backend evaluation working set 保持隔离。

Context Recovery Evidence (verified 2026-08-30 after latest Codex app interruption):

- frontend/backend 共享 Git root，branch 为 `master...origin/master [ahead 50]`，confirmed HEAD 为 `b173e46`，staged diff 为空。最后 verified completed Slice 仍为 5；Slice 6 最近有效 checkpoints 仍为 data `758929d`、read-only UI `ab8f2d9`、control policy `c24e9e5`、cancel/retry `875a0a8` 与 public event/reducer `9bb23c2`，没有重新实现已通过 Gate 的 Slice。
- frontend tracked working set 为本计划和 8 个 TaskPlan frontend 文件，共 9 个文件；其中 `TaskPlanPage` 已按 `currentUser.userId:taskPlanId` 为 `TaskPlanWorkspace` 建立 remount key，真实 App/AuthProvider/Router/QueryClient/MSW test 已验证切换 TaskPlan route 会 abort 旧 confirm stream，且新详情不继承旧 progress/controller。旧 Current Step、Next Action 和 working-set 数量因此过期。
- backend 恢复检查时有 5 个 tracked evaluation 文件修改和 17 个 untracked evaluation builder/report/test/fixture status entries；创建 Slice 6 checkpoint 前又出现第 18 个 untracked evaluation report directory。它们均属于本任务外部 working set，本次恢复未读取其内容、未修改、未暂存。Slice 6 对应 Route/Schema/OpenAPI/contract tests 单独核对，未发现新的 Contract Gap。
- `package.json`、`pnpm-lock.yaml`、`contracts/backend-openapi.json` 与 generated transport types 无工作区差异；Node `24.14.0`、pnpm `10.32.1`、`openapi-typescript@7.13.0`、`react-markdown@10.1.0` 与 `remark-gfm@4.0.1` 保持锁定，`pnpm contracts:check` 通过。
- frontend TaskPlan focused recovery 命令为仓库标准 `pnpm test -- ...`，结果为 5 files / 26 tests 全部通过；确认唯一 confirm Route、`confirmed:true`、request ID/Idempotency-Key、pre-stream 401 replay、409 refetch/no replay、terminal/abort/recovery、安全 404 及 route-boundary abort。
- backend public-event contract 与 validation contract 已通过；批量命令在 resource-visibility test 完成标志输出前结束，因此不把该项误报为已通过，恢复后的唯一 Next Action 从单独重跑该 test 开始，然后执行剩余 Slice Gate。

Context Recovery Evidence (verified 2026-08-30 after Codex app interruption):

- frontend/backend 再次确认共享 Git root，branch 为 `master...origin/master [ahead 50]`，confirmed HEAD 为 `b173e46`；staged diff 为空。最后 verified completed Slice 仍为 5；Slice 6 的 data/read-only/control/cancel-retry/public-event checkpoints 仍为 `758929d`、`ab8f2d9`、`c24e9e5`、`875a0a8`、`9bb23c2`，已通过 Gate 的 Slice 未重新实现。
- frontend tracked working set 为本计划和 7 个 TaskPlan 文件，共 8 个文件；完整 unstaged diff 已读取。backend 无 tracked/staged 修改；17 个 evaluation builder/report/test/fixture status entries 属于外部 working set，本次恢复未读取、修改或暂存。
- package/lockfile/OpenAPI/generated contract 均无工作区差异；Node `24.14.0`、pnpm `10.32.1`、`openapi-typescript@7.13.0`、`react-markdown@10.1.0`、`remark-gfm@4.0.1` 保持锁定，generated types 仍包含 confirm request/operation 与 13 类 `TaskPlanPublicEventFrame`，`pnpm contracts:check` 通过。
- backend `test_agent_task_plan_stream_public_contract.py`、`test_agent_task_plan_validation_contract.py`、`test_agent_task_plan_resource_visibility_contract.py` 使用 repository `.venv` 与 `PYTHONPATH=src` 全部通过，确认 public event projection、安全 422、owned-resource 404 与非流式 `/confirm` 范围边界仍成立。
- frontend TaskPlan focused recovery 使用仓库标准 `pnpm test -- ...` 为 5 files / 25 tests 全部通过；首次 `pnpm exec vitest ...` 因 Windows 下未解析本地 executable 失败，改用 `package.json` 的真实 test script 后通过，不是测试失败。完整 `pnpm check` 通过 contract drift、lint、typecheck、24 files / 110 tests 与 production build。
- Repository/Git/Tests 证明旧“409 ErrorState expected-red”记录已过期：当前实现与测试已显示固定页面消息、安全 code/request ID 且 409 后只 refetch 不 replay。最终源码审查同时确认新的当前缺口：`TaskPlanPage` 未像 Chat route 一样按 `userBoundary:taskPlanId` remount，`TaskPlanDetailView` 仅在 unmount abort，因此 param/user boundary 变化可能保留旧 reducer/controller。恢复后的唯一 Next Action 是先用公开 App/Router seam 固定该行为 expected-red，再做最小 route-identity remount。

Context Recovery Evidence (verified 2026-08-30 after session continuation):

- frontend/backend 再次确认共享 Git root，branch 为 `master...origin/master [ahead 50]`，confirmed HEAD 为 `b173e46`；staged diff 为空。最后 verified completed Slice 仍为 5，Slice 6 最近有效 checkpoints 为 data `758929d`、read-only UI `ab8f2d9`、control policy `c24e9e5`、cancel/retry `875a0a8` 与 public event/reducer `9bb23c2`，已通过 Gate 的 Slice 未重新实现。
- frontend tracked working set 只有 7 个 TaskPlan 文件，包含 generated confirm request alias、唯一 confirm-stream API、独立 reducer local terminals、confirm Dialog、request ID/Idempotency-Key、pre-stream replay、terminal/abort/refetch 与 App/MSW tests；完整 diff/staged diff 已读取。backend 没有 tracked/staged 修改；17 个 evaluation builder/report/test/fixture status entries 属于外部 working set，本次恢复未读取、修改或暂存。
- package/lockfile/generated contract 无工作区差异；Node `24.14.0`、pnpm `10.32.1`、`openapi-typescript@7.13.0`、`react-markdown@10.1.0` 与 `remark-gfm@4.0.1` 保持原锁定状态。generated types 仍包含 `AgentTaskPlanConfirmRequest`、confirm-stream operation 与 13 类 `TaskPlanPublicEventFrame` union，`pnpm contracts:check` 通过。
- backend `test_agent_task_plan_stream_public_contract.py`、`test_agent_task_plan_validation_contract.py` 与使用正确 `PYTHONPATH=src` 的 `test_agent_task_plan_resource_visibility_contract.py` 通过，确认 public event projection、安全 422 与 Initial React Route 统一隐藏式 404 仍成立；首次单独重跑 visibility test 时遗漏 `PYTHONPATH` 导致 import environment error，修正命令后通过，不是代码失败。
- frontend TaskPlan focused recovery 为 5 files / 25 tests 中 24 通过、1 个预期失败：`refetches a conflicting confirm without replaying the stream` 已证明 `409` 后 detail 收敛到 `executing_confirmed` 且未 replay，但页面尚无名为“TaskPlan 确认失败”的共享 `ErrorState` 和安全 error code。Repository/Git/Tests 因此证明旧 Current Step/Next Action 已过期，恢复后的唯一 Next Action 是最小补齐该安全错误展示，再继续同一 Slice Gate。

Slice 6 Public Event/Reducer Evidence (verified 2026-08-29):

- centralized parser expected-red 先因 `parseTaskPlanPublicEvent` 不存在失败；green 后直接引用 generated TaskPlan data/frame/status types，对 status、research/document/requirement/step/sub-question progress、execution/final、answer/sources/guard 及 done/error 13 类 frame 做 runtime allowlist projection。
- 每个 payload 先验证 `contract_version:1.0` 与当前 request ID；known event 只保留明确字段，TaskPlan error 只接受固定安全 message/category，unknown event 只保留 event/request/time/unsupported 投影，额外 Tool/credential payload 不进入对象或 reducer。
- TaskPlan 独立 reducer expected-red/green 覆盖 action request/plan 绑定、status、answer/sources、progress timeline、done/error terminal、other-plan 和 terminal-late isolation；未复用 Chat 业务 reducer。
- focused event/reducer tests 为 2 files / 12 tests 通过，lint/typecheck 通过；完整 `pnpm check` 通过 contract drift、lint、typecheck、24 files / 100 tests 与 production build。该 checkpoint 尚未发送 confirm POST，不声称 transport/UI/abort/refetch 完成。

Slice 6 Cancel/Retry Mutation Evidence (verified 2026-08-29):

- API expected-red 先因 `cancelTaskPlan` 不存在失败；最小 adapter 随后只对 generated `AgentTaskPlanControlResponse` 对应的 cancel/retry Route 发送 `POST`，并原样携带每次 deliberate action 的 `Idempotency-Key`。
- 页面/MSW expected-red 分别证明 retry 和 cancel controls 尚不存在；green 后按 `status + task_kind` 展示操作，retry 与 cancel 提交中均锁定，cancel 必须通过明确 Dialog 确认才调用服务端操作。
- cancel/retry 成功后均 invalidate/refetch 当前用户的 detail/list，不做乐观状态修改；`409` expected-red 先证明两类 Query 未失效，精确增加 conflict refresh 后转为 green。
- focused TaskPlan tests 为 4 files / 12 tests 通过，typecheck/lint 通过；完整 `pnpm check` 通过 contract drift、lint、typecheck、23 files / 94 tests 与 production build。无 package/lockfile/generated/backend 变化，未调用非流式 `/confirm`。

Slice 6 Structured Control Policy Evidence (verified 2026-08-29):

- focused expected-red 先因 `task-plan-controls` module 不存在失败；frontend checkpoint `c24e9e5` 随后建立只依赖结构化 `status` 与 `task_kind` 的 action policy，不解析自然语言 message。
- focused test 1/1 通过，覆盖 research/document 在 waiting、executing、preparing、failed、completed-with-warnings、completed 和 cancelled 状态下的 confirm/retry/cancel 矩阵。
- 完整 `pnpm check` 通过 contract drift、lint、typecheck、22 files / 89 tests 与 production build。该 checkpoint 只完成 action policy，尚未声称页面按钮、mutation、confirm stream 或 manual browser smoke 完成。

Context Recovery Evidence (verified 2026-08-29 before cancel/retry continuation):

- frontend/backend 重新确认共享 Git root，branch 为 `master...origin/master [ahead 45]`，confirmed HEAD 为 `e99a1db89b06d0d221f797f067174c9d7c01289d`；frontend 没有 tracked、staged 或 untracked diff，backend 没有 tracked/staged diff。
- backend 有 16 个 evaluation builder/report/test/fixture 未跟踪文件，不属于 Initial React Slice 6 working set；本次恢复没有读取、修改或暂存它们。
- 最近 checkpoints 与源码一致：`758929d` 为 TaskPlan data seam，`ab8f2d9` 为只读页面，`c24e9e5` 为结构化 action policy，`e99a1db` 为其计划记录；Slice 0-5 的已验证 checkpoints 未被重做。
- package/lockfile 仍精确保留 pnpm `10.32.1`、`openapi-typescript@7.13.0`、`react-markdown@10.1.0` 与 `remark-gfm@4.0.1`；committed OpenAPI/generated types 均存在 `TaskPlanPublicEventFrame` 及 cancel/retry operation，`pnpm contracts:check` 通过。
- frontend focused recovery baseline 为 TaskPlan data/control/workspace 3 files / 7 tests 全部通过。backend `test_agent_task_plan_validation_contract.py` 与 `test_agent_task_plan_resource_visibility_contract.py` 通过，确认 cancel/retry 的安全 422、owned-resource 404 与同 owner 成功基线。
- Repository/Git/Tests 与本计划 Current Slice/Step 一致，未发现过期状态或新 Contract Gap。恢复后唯一 Next Action 仍是为 cancel/retry mutation 的 route/method、pending lock、成功后 detail/list invalidation 及 `409` refetch 建立 focused expected-red，再实现最小 mutation seam；不提前实现 confirm stream。

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
- `docs/DEVELOPMENT.md`
- `docs/features/README.md`
- `docs/features/document-access-grants/feature.md`
- `package.json`
- `pnpm-lock.yaml`
- `contracts/backend-openapi.json`
- `src/api/generated/backend-schema.ts`
- `src/api/api-error.ts`
- `src/api/http-client.ts`
- `../python-agent-study/AGENTS.md`
- `../python-agent-study/learning-docs/教学讲解规范.md`
- `../python-agent-study/src/fast_app/api/document_access_routes.py`
- `../python-agent-study/src/fast_app/schemas/document_access_schema.py`
- `../python-agent-study/src/fast_app/services/knowledge/document_access_service.py`
- `../python-agent-study/src/fast_app/services/knowledge/document_access_repository.py`
- `../python-agent-study/src/fast_app/services/knowledge/document_access_policy.py`
- `../python-agent-study/src/fast_app/services/exceptions.py`
- `../python-agent-study/src/fast_app/core/exception_handlers.py`
- `../python-agent-study/src/fast_app/schemas/error_schema.py`
- `../python-agent-study/scripts/tests/document_security/test_document_access_grants.py`
- `../python-agent-study/scripts/tests/document_security/test_knowledge_document_read.py`
- `../python-agent-study/scripts/tests/agent_research/test_schema_field_descriptions.py`

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
- Slice 2 随后已在 checkpoint `265e900` 完成 AuthProvider、token lifecycle、认证表单与路由保护，10 files / 47 tests 和 browser smoke 通过；Slice 3-8 也已分别通过 Gate，当前为 Slice 9 / IN_PROGRESS；CG009 已关闭，Slice 8 最终 Gate 与 manual smoke 已完成。

Impact:

- 原“所有业务 Slice 均 NOT_STARTED”的实施前警示不再适用；当前进度由本计划的 Slice 状态、Git checkpoints 和实际测试共同证明。

Resolution:

- 由 Slice 1 checkpoint `7cdbcaa` supersede；CG001-CG009 均已按各自批准范围关闭，Slice 2-8 已通过各自 Gate，Slice 8 最终实现链止于 role matrix `c1e037b`；当前 Slice 9 / IN_PROGRESS，只进行 Grant contract reconnaissance。

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

Status: RESOLVED AS ROUTE-SPECIFIC CONTRACT GAPS / DOCUMENT GRANTS PROMOTED TO CG010

Evidence:

- 初始只读 inventory 曾发现 Chat、TaskPlan、User Administration 与 Document Grants mutation 的 422 drift。Chat 已由 CG003、TaskPlan 已由 CG005、User Administration 已由 CG009 改为安全公共 422 contract；Slice 9 已把 Document Grants 风险用真实 Route/OpenAPI/runtime/service/tests 提升为 CG010。
- User Administration 七条 operation 已有批准的 request field allowlist，create/access 另有可判别 business-validation 422 union；CG009 授权未外推到 Grant Route，CG010 随后已获得独立批准并关闭。
- Slice 9 无敏感 TestClient probe 已重新证明 Grant GET/POST/DELETE request validation 只有五个通用 runtime keys、没有 `field_errors`，OpenAPI 仍声明 `HTTPValidationError`；create business 422 还会原样公开 service message，而真实冗余授权分支把 document IDs 拼入该 message。
- User Management feature 明确要求把 `422` 映射到 account、primary department、roles、permissions 等字段；全局 SPEC 对表单 `422` 也要求字段级错误。Chat、TaskPlan 与 Document Grant 的实际字段映射需求现均已在各自 Slice 结合真实交互完成判定。
- Slice 6 reconnaissance 已确认 TaskPlan 不只有 422 drift：detail 200 仍为 arbitrary object，confirm-stream 也只有 generic envelope 且缺少业务 payload schema；对应问题已分别提升为 CG004-CG006。

Impact:

- Slice 8 reconnaissance 曾将 User Management request-validation 与 business-validation 422 风险提升为 CG009并关闭；Slice 9 确认的 CG010 也已由独立 backend/frontend checkpoints关闭。Slice 6 已实际复核并解决 detail type、422 drift 与 business event schema gaps。
- Slice 5 reconnaissance 已确认 `query` 字段确实受影响并提升为 CG003；TaskPlan、User Management 与 Document Grants 后续也分别提升为对应 Route-specific gaps，KI006 不再持有未判定 inventory。
- inventory 未发现新的 Slice 4 Route gap；因此它不阻塞 Slice 4，也不授权提前修改任何未来 backend Route。

Resolution:

- 各项 inventory 均已在对应 Slice 转为明确 gap 或确认不影响；Document Grants 现由 CG010 管理，不再保留为未核实风险。
- 任何既有 Contract Gap 授权都未外推到 Document Grants Route；CG010 只在获得独立用户批准后实施。
- Chat `query` 风险已由严格受限的 CG003 backend checkpoint `d3d95ba` 解决；TaskPlan CG004-CG006 均已按独立授权解决；Admin CG009 已由 backend `9952c69` 与 frontend contract-sync `c6f1645` 关闭；Grant CG010 已由 backend `068e336` 与 frontend contract-sync `967ba14` 关闭。

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

#### CG008 - Knowledge Documents 422 Schema Does Not Match Runtime

Status: RESOLVED

Evidence:

- Initial React Slice 7 使用 `GET /knowledge/documents`、`GET /knowledge/documents/{doc_id}`、`GET /knowledge/documents/{doc_id}/content` 与 `GET /knowledge/documents/{doc_id}/download`；当前四条 Route 的 OpenAPI 422 全部引用 `#/components/schemas/HTTPValidationError`，声明 FastAPI `detail[]`。
- 当前 global validation handler 未为 Knowledge Documents Route 启用安全 projection。真实 Route + handler + dependency override 的 TestClient probe 对 list `limit=0`、invalid `document_type=unsafe_contract_marker` 与 65 字符 path 均返回 `422`，runtime keys 只有 `code/error_category/message/request_id/trace_id`，没有 `detail` 或 `field_errors`，marker 未回显。
- 现有 `test_knowledge_document_read.assert_http_contract()` 与 `assert_cors_contract()` 通过，证明四条 Route、download headers 和 CORS expose baseline；但它只断言 invalid path 的 422 status，没有断言 runtime/OpenAPI 422 schema equality，因此不能关闭该 gap。

Impact:

- generated transport response 与 runtime 不一致；列表页的公开筛选字段无法遵守 approved 422 field-mapping contract，path/content/download validation 也无法使用统一安全 form-level response model。
- Repository rule 明确要求 network behavior 出现 Route/Schema/OpenAPI/tested implementation 冲突时停止并记录 Contract Gap；前端不能通过手写兼容分支或忽略 generated schema 来隐藏冲突。

Recommended Backend Change:

- 复用 CG001-CG005 已建立的安全公共 `RequestValidationErrorResponse` 与 Route/location/field allowlist；只为 `GET /knowledge/documents` 的公开普通 query fields `query`、`department_code`、`document_type`、`limit` 建立明确 field projection。
- `cursor` 是服务端返回的不透明分页值，四条 Route 的 path `doc_id` 也不能安全映射为用户可编辑字段；其 validation error、model-level 与未知错误保持 `field_errors=[]` 的 form-level response。
- 只为上述四条 Initial React Knowledge Documents Route 声明正确的 422 OpenAPI response model；不扩展到 `/knowledge-documents/*` ingestion/admin Route、`/rag/documents/*` compatibility Route、未来 Route 或 mutation endpoints。
- 不读取或回显 validation `input`、`ctx`、raw `msg`、cursor、doc ID、repository path、GitLab URL/token、ACL/grant、正文、secret 或内部字段；增加 runtime/OpenAPI/no-sensitive-echo/form-level/non-allowlisted regression tests。
- 创建只包含 CG008 backend contract fix 的独立 checkpoint；随后重新导出 frontend OpenAPI snapshot/types，运行 contract drift、backend focused regressions 与 `pnpm check`，只有 Runtime = OpenAPI = Tests 后才关闭 CG008 并恢复 Slice 7。

Decision Required:

- 用户已于 2026-08-30 明确批准上述严格受限 backend contract fix；修复已由 backend checkpoint `0676928` 与 frontend contract-sync checkpoint `8072b65` 完成并通过 Runtime/OpenAPI/tests 验证。授权只覆盖四条 Initial React Knowledge Documents GET Route 的安全 422 projection/OpenAPI/tests，未外推到文档 ACL/read/download 业务、ingestion/admin/compatibility/未来 Route 或其他 mutation endpoint。

#### CG009 - User Access 422 Contracts Do Not Support Safe Field Mapping

Status: RESOLVED

Evidence:

- User Access Management feature 要求 `422` 能映射到账号、主部门、角色或权限字段；SPEC 也要求表单 `422` 映射到字段错误。Slice 8 实际使用 catalog、list/detail、create、完整 access PUT、status PATCH 与 reset-password 共 7 条 `/admin/*` Route。
- 当前 7 条 Route 的 OpenAPI `422` 全部引用 `#/components/schemas/HTTPValidationError`，声明 FastAPI `detail[].loc/msg/type`；`user_admin_routes.py` 没有声明安全公共 422 response model，global `_VALIDATION_FIELDS` 也没有任何 Admin Route。
- 无敏感 TestClient probe 对 invalid list `limit/status`、65 字符 path、empty create/access、invalid status 与 empty reset-password 均得到 422；runtime keys 只有 `code/error_category/message/request_id/trace_id`，没有 OpenAPI 声明的 `detail`，也没有安全 `field_errors`。
- create/access 还会由 service 对唯一主部门、部门/角色/直接权限 catalog 与重复 code 等规则抛出 `MANAGED_USER_ACCESS_INVALID / 422`。受控 service probe 证明该 runtime 也只有五个通用字段，无法判别应归属 `account_type`、`department_access` 或 `direct_permission_codes`；2026-08-31 marker probe 进一步确认 service 自然语言 message 会原样进入响应，因此还缺少固定安全 public projection。
- `test_user_administration_read.py` 与 `test_user_administration_write.py` 当前通过，证明管理范围、事务、冲突、自操作、最后管理员、凭证撤销及基础 HTTP 行为没有回退；但 HTTP test 只检查 validation status，不检查 Runtime/OpenAPI shape、no-sensitive-echo 或业务字段映射。

Impact:

- Frontend 若按 generated `HTTPValidationError.detail` 读取会与 runtime 不符；若只显示 form-level message，则 create/access/status/reset-password 不能满足批准的字段级表单行为。
- 前端也不能从自然语言业务 message 猜出主部门、角色或权限字段；这样既不稳定，也会把未经公开模型约束的后端 message 当协议。Catalog/list/detail 的只读 contract reconnaissance 可以完成，但 coherent Slice 8 的 typed mutations、表单与 Gate 被阻塞。

Recommended Backend Change:

- 复用已建立的安全 `RequestValidationErrorResponse`，仅为 User Access 明确批准的公开字段建立 Route/location/field allowlist：list query 的 `query/status/department_code/limit`；create body 的 `username/password/email/display_name/account_type/department_access/direct_permission_codes`；access PUT 的 `account_type/department_access/direct_permission_codes`；status PATCH 的 `status`；reset-password 的 `new_password`。
- 嵌套 `department_access` validation 只能安全折叠为公开顶层 `department_access` 字段；不得回显数组 index、嵌套 path、提交的 department/role code 或原始 Pydantic 位置。`cursor`、path `user_id`、model-level、dependency/header 与未知错误保持 `field_errors=[]` 的 form-level response。
- 为 `ManagedUserAccessInvalidError` 建立独立、安全、可判别的公共 422 response model或等价稳定 projection；field 只能来自 `username/account_type/department_access/direct_permission_codes` 的显式 allowlist。service 必须按确定性业务分支提供稳定 field/code，不允许前端或 handler 解析自然语言 message 推断字段。
- 为 7 条 Initial React User Access Route 声明与 runtime 实际可能返回一致的 422 OpenAPI schema；create/access 需要覆盖 request-validation 与 business-validation 两种安全响应。不得改变用户管理事务、授权范围、catalog、冲突/404/自操作/最后管理员、密码强度或凭证撤销行为。
- 不读取或回显 validation `input`、`ctx`、raw `msg`、password/new_password、email 值、department/role/permission code、token、API Key、ACL、内部信息或未知字段；增加 runtime/OpenAPI/no-sensitive-echo/nested-collapse/form-level/non-Admin-route/regression tests。
- 修复必须形成只包含 CG009 contract fix 的独立 backend checkpoint；随后重新导出 frontend OpenAPI snapshot/types，运行 contract drift、User Administration focused regressions 与 `pnpm check`。只有 Runtime = OpenAPI = Tests 后才能关闭 CG009 并恢复 Slice 8。

Decision:

- 用户于 2026-08-31 明确批准上述严格受限 backend contract fix。授权只覆盖七条 Initial React User Access Route 的安全 request/business 422 projection、OpenAPI schema 与 runtime/OpenAPI/no-sensitive/nested-collapse/form-level/non-Admin/regression tests；不得改变用户管理事务、授权范围、catalog、冲突/404/自操作/最后管理员、密码强度、凭证撤销或其他 Admin/Grant/未来 Route。
- CG009 必须形成只包含该 contract fix 的独立 backend checkpoint；随后重新导出 frontend OpenAPI snapshot/generated types并通过 contract drift、focused regressions 与 `pnpm check`，只有 Runtime = OpenAPI = generated types = Tests 后才可关闭 CG009 并开始 Slice 8 frontend business implementation。

Resolution:

- backend checkpoint `9952c69` 为七条 User Administration operation 建立安全 request 422 contract，为 create/access 建立按顶层 `code` 判别的 request/business union，并让 nested `department_access` 只折叠到批准顶层字段；path/dependency/malformed/unknown 与非 Admin Route 保持 form-level或原有 shape。
- service 的每个 `ManagedUserAccessInvalidError` 分支显式提供批准 field 与稳定 code，public response 使用固定通用 message，不再公开或解析自然语言业务 message；runtime/OpenAPI/no-sensitive/nested-collapse/non-Admin/shared regressions 全部通过。
- frontend sync checkpoint `c6f1645` 从 backend `9952c69` 导出 58 paths / 138 schemas并生成 discriminated transport union；contract drift 与最终完整 `pnpm check` 通过。CG009 关闭，Slice 8 恢复正常 frontend implementation。

#### CG010 - Document Grants 422 Contracts Drift and Echo Document IDs

Status: RESOLVED

Evidence:

- Cross-Department Document Grants feature 的 create form 使用精确 `target_account` 与 1–100 个唯一 `document_ids`；全局 SPEC 要求 `422` 映射到字段错误，并要求只展示服务端安全错误。Slice 9 实际使用 Grant list GET、create POST 与 revoke DELETE 三条 Route。
- 当前三条 Route 的 OpenAPI `422` 全部引用 `#/components/schemas/HTTPValidationError`，声明 FastAPI `detail[].loc/msg/type`；`document_access_routes.py` 没有声明安全公共 422 response model，global `_VALIDATION_FIELDS` 也没有 Grant Route。
- 无敏感 TestClient probe 对 invalid list `limit`、duplicate create `document_ids` 与 65 字符 revoke path 均返回 `422`，runtime keys 只有 `code/error_category/message/request_id/trace_id`，既没有 OpenAPI 声明的 `detail`，也没有 `field_errors`。
- create 还会因 public、同部门或原始 ACL 已可读而抛出 `DOCUMENT_ACCESS_GRANT_INVALID / 422`。受控 marker probe 证明该异常 message 会由公共 handler 原样返回；真实 service 又把冗余 `document_ids` 拼入 message，因此当前 runtime 会把提交的文档标识作为未经 allowlist 的自然语言协议公开。list 的无效 cursor 复用同一异常，但应保持安全 form-level 语义。
- `test_document_access_grants.py` 当前通过并证明部门范围、原子/幂等创建、撤销、public 与即时读取 baseline；其 HTTP test 只断言 duplicate body 的 status 为 422 和 OpenAPI path 存在，不检查 Runtime/OpenAPI shape、field mapping、business no-echo 或公共 response schema。`test_schema_field_descriptions.py` 与 `test_knowledge_document_read.py` 也通过，未关闭该 gap。

Impact:

- Frontend 若按 generated `HTTPValidationError.detail` 读取会与 runtime 不符；若只显示 form-level，则 `target_account/document_ids` create form 不能满足批准的字段级 422 行为。
- 前端不能解析自然语言 business message 来推断 `document_ids`；继续使用该 message 既不稳定，也会把未经公开 schema 约束的 document IDs 渲染到页面。Coherent Slice 9 的 typed adapters、create/revoke UI 与 Gate 因此被阻塞。

Recommended Backend Change:

- 复用既有安全 `RequestValidationErrorResponse`，只为三条 Initial React Grant Route 建立明确 Route/location/field allowlist：list query 的 `target_account/doc_id/status/department_code/limit`；create body 的 `target_account/document_ids`；revoke path、`cursor`、model-level、dependency/header、malformed 与未知错误保持 `field_errors=[]` 的 form-level response。
- `document_ids` 的 item-level validation 只折叠为公开顶层 `document_ids`，不得公开数组 index、提交值、raw Pydantic loc/msg/input/ctx。公共 field enum 只新增该范围实际需要的 `target_account/doc_id/document_ids`；既有 `status/department_code/limit` 继续复用。
- 为 `DocumentAccessGrantInvalidError` 建立独立、安全、可判别的公共 422 response 或等价稳定 projection：冗余授权分支显式提供 allowlisted `document_ids` field 与稳定 code；invalid cursor 保持无 field 的 form-level。handler 不解析自然语言 message，公共 message 必须固定且不得包含 document ID、target account、ACL、部门、repository path 或其他提交/内部值。
- GET/POST 的 OpenAPI 422 必须表达 runtime 可能返回的 request/business safe response，DELETE 只声明安全 request-validation response；增加 runtime/OpenAPI/no-sensitive-echo/nested-collapse/form-level/non-Grant-route regressions。不得改变 grant authorization、manager department scope、target resolution、public/同部门/ACL redundancy policy、transaction、idempotency、conflict/403/404、audit record、revoke 或 retrieval behavior。
- 修复必须形成只包含 CG010 contract fix 的独立 backend checkpoint；随后重新导出 frontend OpenAPI snapshot/generated types，运行 contract drift、Grant/Knowledge Documents/shared validation focused regressions 与 `pnpm check`。只有 Runtime = OpenAPI = generated types = Tests 后才能关闭 CG010 并开始 Slice 9 frontend business implementation。

Decision:

- 用户于 2026-09-01 明确批准上述 CG010 严格受限 backend contract fix。授权只覆盖三条 Initial React Grant Route 的安全 request/business 422 projection、必要 exception field metadata、OpenAPI schema 与 runtime/OpenAPI/no-sensitive/nested-collapse/form-level/non-Grant/regression tests。
- CG010 必须形成独立 backend checkpoint；随后重新导出 frontend snapshot/generated types并通过 contract drift、focused regressions 与 `pnpm check`。Runtime = OpenAPI = generated types = Tests 前不创建 Grant frontend DTO、Query 或页面。

Resolution:

- backend checkpoint `068e336` 为三条 Grant operation建立安全 request validation projection，为 GET/POST 建立按 `code` 判别的 request/business 422 union，并让 cursor、path、malformed、unknown与无关 Route保持 form-level或原有 shape。
- `DocumentAccessGrantInvalidError` 只接受 `document_ids/invalid` 或无 field，handler使用固定安全 public message；真实冗余授权分支不再把 document IDs拼入 exception/public/log message。runtime/OpenAPI/no-sensitive/form-level/non-Grant/shared regressions全部通过。
- frontend sync checkpoint `967ba14` 从 backend `068e336` 导出 58 paths / 140 schemas并生成判别 transport union；contract drift与完整 `pnpm check`通过。CG010关闭，Slice 9恢复正常 frontend implementation。

#### CG011 - No Server-Trimmed Grantable Document Selection Contract

Status: RESOLVED

Evidence:

- Cross-Department Document Grants feature要求创建时从知识文档中选择 1–100 篇 non-public文档；主管的可选文档必须由其主管部门范围限制，管理员可按部门筛选。当前 Grant backend只公开 grant record GET、create POST与revoke DELETE，没有document selection/catalog Route。
- `KnowledgeDocumentItem` transport没有 `visibility`或 grant-management eligibility。管理员的read scope会在 public判断之前返回 `access_source=admin`；真实 Knowledge Documents test明确断言管理员列表所有item都是 `admin`，所以不能用 `access_source`排除public。
- 主管的 Knowledge Documents read scope还可包含 `original_acl`和 `explicit_grant`外部门文档，而 Grant create service独立要求主管只能授权自己 primary department拥有的文档。现有列表因此不能代表可管理范围；detail的 `visibility`也不能补足backend management-scope裁决。
- backend `get_grantable_documents(doc_ids)`只在create提交后读取指定active文档，随后service才检查actor scope、public/同部门/original ACL redundancy与target account。它不是可分页、可筛选、server-trimmed的选择contract。

Impact:

- Frontend不能同时满足“只选择non-public”“主管只看到可管理部门文档”“不计算客户端ACL/权限”和“不得任意输入doc ID”。继续实现会把read scope误当management scope、向管理员展示public候选或让主管选择其仅可读但不可授权的外部门文档。
- 逐项请求 Knowledge Document detail只能得到raw visibility，仍无法得到actor grant-management裁决；用AuthProvider部门/账号类型自行比较则会复制backend authorization policy。Slice 9 create draft/Dialog因此阻塞；已完成的read-only grant list不受影响。

Recommended Backend Change:

- 在既有 `/admin/document-access` 边界新增只读、server-trimmed的 grantable-document catalog Route（推荐 `GET /admin/document-access/grantable-documents`），支持opaque cursor、limit、文本筛选与管理员可用的 `department_code`；主管的department scope必须由backend固定，不能由客户端提交扩大。
- response只返回创建选择需要的安全字段，例如 `doc_id/title/repository_path/document_department_code/document_type`；只列active、non-public且actor有权管理的文档，不返回ACL、allowed users、visibility原值、内部source配置或任意权限集合。该catalog不新增用户搜索，也不替代create时针对target account的最终public/同部门/original ACL/active grant/transaction校验。
- 增加manager/admin/employee scope、public exclusion、manager department fixation、admin department filter、opaque cursor/filter、OpenAPI/runtime/no-sensitive-field tests；形成独立backend checkpoint。随后重新导出frontend OpenAPI snapshot/types并通过contract drift、Grant/Knowledge Documents regressions与 `pnpm check`，再恢复create draft TDD。

Decision:

- 用户于2026-09-01明确批准上述Recommended Backend Change。范围严格限定为只读selection catalog、安全字段、backend-fixed scope/public exclusion、cursor/filter、validation/OpenAPI/tests与后续frontend contract sync；CG010授权未被扩大，Runtime = OpenAPI = generated types = Tests前不恢复Grant create UI。

Resolution:

- backend checkpoint `ea6df62`实现唯一只读grantable-document catalog及安全schema、服务端actor scope/public exclusion、filter/keyset cursor与runtime/OpenAPI/no-sensitive regressions；既有create/revoke、Knowledge Documents read与RAG/Agent边界未改变。
- frontend sync checkpoint `03170c7`只更新canonical OpenAPI snapshot/generated types；contract drift、Grant/Knowledge Documents focused与完整`pnpm check`通过。CG011关闭，唯一Next Action恢复为新catalog的frontend data/query expected-red。

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

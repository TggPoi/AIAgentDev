# React 前端后端接口 TodoList

> 上下文压缩或新会话开始时，先读取同目录的
> `REACT_FRONTEND_BACKEND_IMPLEMENTATION_HANDOFF.md`。当前前端工程中的
> `SPEC.md`、`ARCHITECTURE.md` 和 feature 文档只是后端接口完成前的草案，
> 不能用于开始 React 编码；后端 P0 完成后必须基于真实契约重新生成。

## 1. 用途

本文件是 React 前端所需后端 interface 的唯一实施清单，用来在长任务、会话切换或上下文压缩后恢复真实进度。

状态规则：

- `❌`：缺失、契约不完整、尚未测试，或尚未通过对应 feature 验收。
- `✅`：实现完成、权限与失败路径测试通过、OpenAPI/事件契约已核对、实施记录已更新。前端 feature 文档统一在后端 P0 全部完成后重新生成。

不能因为路由文件已经创建就标记 ✅。每完成一项，必须在“实施记录”填写日期、变更文件和实际运行的验证命令。

## 2. 已确认可复用的现有 interface

以下接口已经存在，后续只在有明确待办时扩展；React RAG 问答仍只接入结构化流接口。

- ✅ `POST /auth/login`：用户名/邮箱和密码登录，返回 access/refresh token。
- ✅ `POST /auth/refresh`：轮换 refresh token。
- ✅ `GET /auth/me`：返回当前认证用户基础身份；前端所需字段扩展另列待办。
- ✅ `POST /rag/chat/stream/events`：React 唯一 RAG / Agent 问答入口。
- ✅ `GET /nl2sql/datasets`：返回当前用户获准使用的 Dataset。
- ✅ `GET /agent/task-plans/{task_plan_id}`：读取单个 TaskPlan。
- ✅ `GET /agent/task-plans/{task_plan_id}/markdown`：读取 Markdown 审查视图。
- ✅ `POST /agent/task-plans/{task_plan_id}/confirm/stream`：确认并流式观察执行。
- ✅ `POST /agent/task-plans/{task_plan_id}/cancel`：取消 TaskPlan。
- ✅ `POST /agent/task-plans/{task_plan_id}/retry`：重试 TaskPlan。

以下接口明确不接入 React 问答 UI：

```text
POST /rag/chat
POST /rag/chat/stream
POST /rag/search
POST /rag/search/stream
POST /nl2sql/query
```

## 3. P0：身份与能力

### ✅ `GET /auth/me` 前端身份字段扩展

上下文：现有响应可确认用户 ID、全局角色、全局权限和部门，但缺少稳定的 `username`、三类账号类型和完整部门作用域权限视图。

为什么需要：应用顶栏、权限管理详情和路由保护需要服务端身份快照；前端不能根据若干 role code 自行猜测账号类型。

实现方案：

1. 在认证领域模型和响应 schema 中补充 `username`、`account_type`、`department_permission_codes`。
2. `account_type` 由服务端角色策略计算，只允许 `admin / department_manager / employee`。
3. 保持现有字段向后兼容，并为所有新增 Pydantic 字段提供 `Field(description=...)`。

权限与失败：只返回当前认证用户；匿名或失效凭证返回统一 401。

验收：三类用户的响应与数据库角色事实一致，不能通过 JWT 客户端 payload 伪造。

实施记录：2026-08-24 完成。新增 `20260824_0015` 迁移、`department_manager` 角色、用户直接权限事实表和可审计文档授权事实表；扩展 `CurrentUserContext`、`AuthService` 与 `CurrentUserResponse`，由数据库 RBAC 实时推导 `username`、`account_type` 和 `department_permission_codes`。已运行身份 HTTP 契约、Schema 字段说明、RBAC 数据库集成、迁移 downgrade/upgrade 往返、现有 Agent Tool 权限回归和主应用 OpenAPI 检查，均通过。

### ✅ `GET /auth/capabilities`

上下文：React 需要决定是否显示用户管理、跨部门授权、联网搜索、NL2SQL 和文档操作入口，当前只能硬编码 permission code。

为什么需要：把业务授权规则集中在后端，提高 interface 深度；前端 capability 只负责显示，写接口仍执行同样的后端权限检查。

实现方案：根据 `CurrentUserContext` 和有效部门权限返回布尔 capability 与用户管理范围，例如：

```text
can_manage_users
user_management_scope: all | own_department | none
can_manage_document_grants
can_use_web_search
can_use_nl2sql
can_read_documents
can_manage_documents
```

权限与失败：只允许已认证用户；不返回内部角色表、GitLab Token 或其他用户权限。

验收：capability 与实际接口 403 结果一致；前端隐藏入口后，伪造请求仍被后端拒绝。

实施记录：2026-08-24 完成。新增 `capability_service.py`，从可信账号类型、全局有效权限和部门作用域权限生成七项非敏感 capability；匿名身份返回统一 401，三类账号策略、响应字段说明及 OpenAPI 路径已通过回归。Capability 只控制前端展示，后续管理写接口仍必须复用相同服务端身份策略独立鉴权。

### ✅ `POST /auth/logout`

上下文：前端只删除本地 token 不能撤销仍然有效的 refresh token。

为什么需要：提供真实服务端注销，使泄露或被复制的 refresh token 在注销后不能继续轮换。

实现方案：请求携带当前 refresh token，后端校验归属并幂等撤销；响应不返回凭证。是否支持“注销全部设备”后续单独扩展。

权限与失败：已经撤销的 token 再次注销仍返回成功；伪造或不属于当前用户的 token 返回统一认证错误。

验收：注销后原 refresh token 无法换取新 access token。

实施记录：2026-08-24 完成。新增归属校验后的 refresh token 服务端撤销，当前用户重复注销同一 revoked token 幂等成功，伪造或其他用户 token 返回统一 `AUTHENTICATION_FAILED`。已通过数据库凭证失效测试、HTTP 200/401 契约和主应用 OpenAPI 检查。

### ✅ `POST /auth/change-password`

上下文：账号只能由管理员创建，用户仍需要在登录后修改初始密码。

为什么需要：避免长期使用管理员传递的初始密码。

实现方案：校验当前密码、密码强度与新旧不同，更新 Argon2 hash，并按确定策略撤销该用户已有 refresh token。

权限与失败：只允许当前认证用户修改自己；错误当前密码使用稳定 error code，不泄露 hash 信息。

验收：修改后旧密码登录失败，新密码成功，旧 refresh token 按策略失效。

实施记录：2026-08-24 完成。新增 12–128 位且同时包含大小写字母、数字和符号的新密码策略；错误当前密码返回 `AUTH_CURRENT_PASSWORD_INVALID`，相同或弱密码返回 `AUTH_PASSWORD_POLICY_FAILED`。密码 hash 更新和该用户全部 active refresh token 撤销位于同一事务；已验证旧密码、旧 refresh token 失效及新密码登录成功。

## 4. P0：用户与功能权限管理

### ✅ `GET /admin/access/catalog`

上下文：创建和编辑用户时需要部门、账号类型及可下放权限目录。

为什么需要：前端不能硬编码“主管可以授予哪些权限”，否则后端策略变化后 UI 会漂移。

实现方案：根据 actor 返回裁剪后的部门、账号类型、功能权限、Agent Tool 权限和部门文档操作权限；每项包含 code、名称、说明和风险级别。

权限与失败：管理员看到全量可管理目录；部门主管只看到自己部门及允许下放给普通员工的权限；普通员工返回 403。

验收：部门主管响应中不包含管理员角色、主管角色或不可下放权限。

实施记录：2026-08-24 完成。新增用户管理深模块，管理员获得全部三类账号、全部部门及四项可直接下放功能权限；主管目录固定为自己的主部门、employee 账号和不含高风险 MCP 的可下放权限。普通员工/匿名 actor 由模块策略返回稳定 403。Schema 字段说明、OpenAPI 和目录裁剪测试通过。

### ✅ `GET /admin/users`

上下文：缺少管理范围内用户的分页列表。

为什么需要：管理员和主管需要查找、筛选和进入用户详情。

实现方案：支持 `cursor`、`limit`、`query`、`status`、`department_code`；返回稳定 `next_cursor`。管理员查询全平台，主管的 department filter 由服务端固定为自己主部门。

权限与失败：普通员工 403；主管不能通过 query 参数扩大部门范围。

验收：跨部门数据隔离、分页无重复、禁用用户可筛选。

实施记录：2026-08-24 完成。实现 `updated_at + user_id` 不透明 keyset cursor、1–100 limit、文本/状态/部门筛选；主管部门由服务端固定，并在 PostgreSQL 查询中排除管理员和其他主管。非法 cursor 和主管扩大部门范围具有稳定错误码；真实 PostgreSQL adapter 查询与模块 interface 测试通过。

### ✅ `GET /admin/users/{user_id}`

上下文：编辑页面需要目标用户的基本信息、账号类型、部门、直接授权和有效权限。

为什么需要：列表摘要不能承担完整 access snapshot，也不能让前端拼接多组授权事实。

实现方案：由 User Administration module 聚合用户、部门、角色和直接权限，返回一个可审查快照。

权限与失败：管理员可查全部；主管只可查本部门普通员工；目标不存在或不可见按统一资源隐藏策略返回 404/403。

验收：主管不能通过已知 user ID 查看其他部门或高权限账号。

实施记录：2026-08-24 完成。详情聚合基本身份、服务端推导账号类型、全局角色、active 直接权限、有效全局权限及各部门角色/权限。管理员可查看全部；主管仅可查看自己主部门 employee，外部门或高权限目标返回 403，缺失目标返回 404。OpenAPI、Schema 和模块 interface 测试通过。

### ❌ `POST /admin/users`

上下文：当前 `AuthService.create_user()` 仅供初始化脚本或内部复用，没有管理路由和三类账号约束。

为什么需要：系统明确禁止自助注册，账号创建必须有受控前端入口。

实现方案：在一个事务内创建用户、绑定主部门、账号角色和初始直接权限；用户名/邮箱先规范化，密码只保存 Argon2 hash。

权限与失败：管理员可创建三类账号；主管只能创建自己部门的 employee；冲突返回 409，越权返回 403。

验收：任何后续授权写入失败时，用户记录也回滚；主管不能伪造 department/account_type。

实施记录：未开始。

### ❌ `PUT /admin/users/{user_id}/access`

上下文：功能、Agent Tool 和部门文档操作权限需要可重复保存的编辑 interface。

为什么需要：逐条 grant/revoke 容易部分成功；完整 access snapshot 更适合表单提交和事务验证。

实现方案：接收完整 snapshot，在单事务中校验并原子替换账号类型、部门角色和直接功能权限。跨部门文档 grant 不放进此接口。

权限与失败：主管只能修改自己部门 employee，且只能分配 catalog 中允许下放的权限；管理员不能意外移除自己的最后一个系统管理员能力，需要服务端保护。

验收：失败回滚、重复提交幂等、越权字段不能静默忽略。

实施记录：未开始。

### ❌ `PATCH /admin/users/{user_id}/status`

上下文：需要启用和禁用账号。

为什么需要：删除账号会破坏审计和历史归属，状态切换更适合企业账号生命周期。

实现方案：只接受 `active / disabled`；禁用时撤销 refresh token，并确定 API Key 的失效策略；记录 actor 和 request ID。

权限与失败：主管只能操作本部门 employee；用户不能禁用自己；不能禁用系统最后一个管理员。

验收：禁用用户已有 access/refresh/API Key 按策略停止工作，重新启用不恢复已撤销凭证。

实施记录：未开始。

### ❌ `POST /admin/users/{user_id}/reset-password`

上下文：无自助找回密码，管理员或主管需要为管理范围内账号重置初始密码。

为什么需要：覆盖忘记密码和新用户首次交付场景。

实现方案：校验新密码策略，更新 hash，撤销现有 refresh token；不在响应或日志重复返回密码。

权限与失败：管理员可重置管理范围内账号；主管只可重置本部门 employee；不能重置管理员或其他主管。

验收：越权重置失败，旧密码与旧 refresh token 均失效。

实施记录：未开始。

## 5. P0：跨部门文档授权

### ❌ `GET /admin/document-access/grants`

上下文：目标文档所属部门主管需要查看自己部门文档已经授予哪些外部门用户。

为什么需要：授权必须可审计、可筛选、可撤销，不能只保留在聊天或前端状态。

实现方案：支持 `cursor`、`limit`、`target_account`、`doc_id`、`status`；主管的文档部门范围由服务端固定，管理员可按部门筛选。

权限与失败：主管不能读取其他部门 grant；响应只返回完成授权管理所需的目标用户最小信息。

验收：主管列表中只出现自己部门拥有文档的 grant。

实施记录：未开始。

### ❌ `POST /admin/document-access/grants`

上下文：用户访问其他部门文档时，需要由文档所属部门主管单独授权。

为什么需要：用户部门归属不应因为读取一篇外部门文档而改变，也不能因此获得该部门全部文档。

实现方案：请求使用目标用户精确账号标识和 `document_ids`；在一个事务内校验用户有效、文档 active、每篇文档属于 actor 可管理部门，并创建带 actor/time 的 grant。

权限与失败：管理员可授权任意文档；主管只能授权自己部门文档；重复 active grant 幂等返回已有结果或稳定冲突。

验收：授权后目标用户仅获得指定 doc_id，文档列表、详情、下载和 RAG 同时生效。

实施记录：未开始。

### ❌ `DELETE /admin/document-access/grants/{grant_id}`

上下文：跨部门访问必须可撤销。

为什么需要：物理删除会丢失审计，保留 revoked 状态才能追踪历史。

实现方案：幂等标记 revoked_by/revoked_at；权限判断和检索只读取 active grant。

权限与失败：只有管理员或 grant 文档所属部门主管可撤销。

验收：撤销后列表、详情、下载和 RAG 权限立即同时失效，历史审计仍存在。

实施记录：未开始。

### ❌ Document Access Policy 与检索下推

上下文：这不是新 URL，但决定上述 grant 是否真正影响 RAG。

为什么需要：只给文档页面加权限会造成“页面可读但 RAG 搜不到”；只给检索加权限会造成下载越权。

实现方案：建立共享 Document Access Policy，合并 public、用户本部门和 active cross-department doc IDs；ES 使用 doc_id terms，Milvus 使用 doc_id in，与现有 ACL 条件做 OR。

验收：使用同一组测试数据同时验证列表、详情、下载、Keyword、Vector、Hybrid 和父块扩展。

实施记录：未开始。

## 6. P0：会话管理

### ❌ `GET /conversations`

上下文：侧边栏需要当前用户自己的持久化会话列表。

为什么需要：浏览器本地列表不能跨设备恢复，也不能作为权限事实。

实现方案：keyset/cursor 分页，按 `updated_at + id` 稳定倒序；返回标题和最后消息摘要，不返回完整消息。

权限与失败：只按当前认证 user ID 查询，不接受客户端 user ID。

验收：不同用户会话完全隔离，翻页期间无重复或漏项。

实施记录：未开始。

### ❌ `POST /conversations`

上下文：发送第一条消息前需要稳定外部 `session_id`。

为什么需要：由服务器生成 ID 可以统一长度、字符和审计，前端无需自己猜测内部 scoped ID。

实现方案：生成外部 session ID，保存用户归属、默认标题和时间；内部 ID 继续由 user ID + session ID 映射。

权限与失败：只允许认证用户创建自己的会话。

验收：并发创建 ID 唯一，新会话可立即读取。

实施记录：未开始。

### ❌ `PATCH /conversations/{session_id}`

上下文：用户需要重命名侧边栏会话。

为什么需要：标题属于会话容器，不应伪装成一条聊天消息。

实现方案：只更新经过长度和空白校验的 title，保持 session ID 和消息不变。

权限与失败：只能修改当前用户会话。

验收：越权失败，重命名后列表顺序和消息不受影响。

实施记录：未开始。

### ❌ `DELETE /conversations/{session_id}`

上下文：删除 PostgreSQL 会话而保留 Redis 近期窗口会让复用 ID 继承旧上下文。

为什么需要：删除必须覆盖 durable storage 和短期 memory。

实现方案：删除当前用户 conversation/message/summary，并通过 ConversationMemoryStore interface 清理 Redis 或内存 key；操作幂等。

权限与失败：不能删除他人会话。

验收：删除后历史接口为空/404，复用旧 ID 不读取旧近期消息。

实施记录：未开始。

### ❌ `GET /conversations/{session_id}/messages`

上下文：刷新和历史滚动需要读取持久化消息。

为什么需要：SSE 只传输当前请求，不能替代历史读取。

实现方案：按稳定 message sequence cursor 分页；返回 user/assistant 内容、来源、TaskPlan ID、终态和时间。

权限与失败：按 current user + scoped conversation ID 联合查询。

验收：消息顺序稳定，两个用户的同名 session 不会串数据。

实施记录：未开始。

### ❌ 统一 `/rag/chat/stream/events` 会话落库契约

上下文：React 只调用结构化流接口，因此只需保证这条入口无论内部选择哪个 pipeline provider，都能形成一致的持久化 turn。

为什么需要：前端不接其他 RAG 接口，但结构化流内部 provider 变化不能导致历史行为漂移。

实现方案：在结构化流应用边界集中定义一次 turn 的保存时点、字段和幂等键；避免与现有 RagAgent 内部持久化重复写入。

验收：针对结构化流分别验证当前支持的 provider，完成、error、abort 和 TaskPlan 等路径的历史结果符合明确契约。

实施记录：未开始。

## 7. P0：知识文档读取

### ❌ `GET /knowledge/documents`

上下文：GitLab 文档事实表存在，但没有面向用户的 ACL 文档目录。

为什么需要：文档模块和 Agent 来源跳转都需要稳定列表 interface。

实现方案：支持 `cursor`、`limit`、`query`、`department_code`、`document_type`；查询 active 正式文档并应用共享 Document Access Policy。

权限与失败：只允许认证用户；客户端 department filter 只能缩小范围。

验收：同部门全量可见，其他部门只有 explicit grant 文档可见。

实施记录：未开始。

### ❌ `GET /knowledge/documents/{doc_id}`

上下文：现有 `/rag/documents/{doc_id}` 是未接真实 GitLab ACL 的开发接口，不能供 React 使用。

为什么需要：详情页需要固定的文档元数据和 source revision。

实现方案：从 GitLab 文档表和 source 表聚合标题、路径、部门、类型、revision、更新时间和授权来源。

权限与失败：复用共享 Document Access Policy；不可见文档按统一资源隐藏策略响应。

验收：已知 doc ID 不能绕过列表 ACL。

实施记录：未开始。

### ❌ `GET /knowledge/documents/{doc_id}/content`

上下文：前端需要阅读 Markdown/TXT 和 Office/PDF 文档，但不能直接拿 GitLab Token。

为什么需要：建立受 ACL 保护的只读预览 interface。

实现方案：后端按文档记录的固定 revision 获取源文件；Markdown/TXT 返回文本，PDF/DOCX/PPTX/XLSX 使用现有解析依赖生成有界文本预览，返回 `render_mode` 和 warnings。

权限与失败：校验 ACL、文件大小、支持类型和外部 GitLab 错误；不把任意 HTML 标为可信。

验收：预览 revision 与详情一致，超限和不支持格式返回稳定错误。

实施记录：未开始。

### ❌ `GET /knowledge/documents/{doc_id}/download`

上下文：用户需要下载 GitLab 源文件。

为什么需要：浏览器不能访问私有 GitLab 或接触服务器 Token。

实现方案：按固定 revision 获取 bytes，使用净化 basename、正确 Content-Type/Disposition 和有界响应；失败统一翻译。

权限与失败：与 content 使用同一 ACL；不能通过路径参数或 header 改写 repository path/ref。

验收：越权下载失败，文件名无 header/path traversal，内容与 revision 一致。

实施记录：未开始。

## 8. P0：TaskPlan 恢复

### ❌ `GET /agent/task-plans`

上下文：当前只能按已知 ID 查询，刷新页面后无法发现未完成计划。

为什么需要：等待确认、执行中和失败可重试任务需要持久任务视图。

实现方案：支持 `cursor`、`limit`、`status`、`session_id`，返回安全 public summary 和 `next_cursor`。

权限与失败：普通用户只看自己的计划；管理员跨用户能力由明确 query 和权限控制，默认不放开。

验收：刷新后能找回 waiting/executing/failed 任务，计划内部敏感事实不泄露。

实施记录：未开始。

## 9. P0：结构化流与来源契约

### ❌ `POST /rag/chat/stream/events` 前端契约固化

上下文：路由已经存在，但 StreamingResponse 的事件 payload 不能仅靠前端阅读实现代码猜测。

为什么需要：跨 chunk parser、事件 reducer、错误恢复和后端演进都需要可测试的稳定 contract。

实现方案：

1. 为公开事件建立版本化 envelope 或可生成样例的 Pydantic contract。
2. 固定 `answer_delta`、`sources`、TaskPlan、NL2SQL、Guard、`done`、`error` 的必需字段。
3. HTTP Response Header 暴露 request ID；SSE error 保持统一错误字段。
4. 写 contract test 覆盖事件顺序、未知事件兼容和终态。

权限与失败：仍由当前认证、Dataset scope、Tool permission 和 Prompt Guard 执行；前端不能提交服务端权限字段。

验收：前端 fixture 来自真实后端 schema/测试样例，不手写另一套漂移协议。

实施记录：未开始。

### ❌ `RagSource` 稳定导航字段

上下文：当前 `doc_id` 已存在，但网页 URL 主要依赖无类型 metadata，前端会被迫猜 key。

为什么需要：文档与网页来源需要稳定、可判别、可点击的 interface。

实现方案：向后兼容增加 `source_type: knowledge_document | web` 和 `href`；文档来源 href 指向前端可构造的 doc ID 语义或保持 null，网页来源 href 由后端校验后返回。

验收：前端不读取任意 metadata URL；文档和网页来源均有 contract test。

实施记录：未开始。

## 10. 实施顺序

1. 身份字段、capability、部门主管角色与授权事实表。
2. 用户管理和跨部门文档 grant。
3. 共享 Document Access Policy，并先验证 ES/Milvus 与文档读取一致性。
4. 文档列表、详情、预览和下载。
5. 会话 CRUD、历史和结构化流统一落库。
6. TaskPlan 列表。
7. SSE/RagSource contract 固化与完整回归。
8. P0 全部 ✅ 后，开始 React 工程编码。

## 11. 进度汇总

| 分组 | 已完成 | 待完成 |
| --- | ---: | ---: |
| 可复用现有 interface | 10 | 0 |
| 身份与能力 | 4 | 0 |
| 用户与功能权限 | 3 | 4 |
| 跨部门文档授权 | 0 | 4 |
| 会话管理 | 0 | 6 |
| 知识文档 | 0 | 4 |
| TaskPlan 恢复 | 0 | 1 |
| 结构化流与来源契约 | 0 | 2 |

最后更新：2026-08-24，身份与能力 4/4、用户与功能权限管理 3/7；下一切片实现用户创建、access 原子替换、状态和重置密码。React 文档仍是待后端 P0 完成后重新生成的草案。

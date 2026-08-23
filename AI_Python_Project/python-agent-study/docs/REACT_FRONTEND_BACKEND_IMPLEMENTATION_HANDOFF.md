# React 前端配套后端接口实施交接

## 1. 交接目的

本文件用于在上下文压缩后恢复 React 配套后端与前端规范工作的真实状态。应先从本文、`BACKEND_INTERFACE_TODO.md` 和当前代码恢复事实，不得重复已完成的后端切片。

生成时间：2026-08-24。

当前状态：后端 P0 全部完成；React `SPEC.md`、`ARCHITECTURE.md` 和 10 个 feature 规范已按真实契约重新生成，等待用户确认。尚未创建 React 源码或安装依赖。

## 2. 压缩后读取顺序

在采取任何代码操作前，按以下顺序读取：

1. `AGENTS.md`
2. `learning-docs/教学讲解规范.md`
3. `docs/REACT_FRONTEND_BACKEND_IMPLEMENTATION_HANDOFF.md`
4. `docs/BACKEND_INTERFACE_TODO.md`
5. 当前准备修改的真实代码、迁移和测试
6. `git status --short` 与目标文件的现有 diff

代码和 TodoList 冲突时，以当前代码事实为准，先修订 TodoList 中的上下文，再实施；不能让过期计划驱动代码。

## 3. 当前权威范围

### 3.1 后端实施唯一 TodoList

```text
python-agent-study/docs/BACKEND_INTERFACE_TODO.md
```

TodoList 当前记录 10 个原有可复用接口和 28 个 P0 项；28 个 P0 项已经全部标记为 ✅。后续若发现真实契约缺陷，必须重新记录上下文、实现和验证，不能只修改状态符号。

### 3.2 前端文档已重新生成，等待确认

`react-agent-frontend/docs/` 下 `SPEC.md`、`ARCHITECTURE.md` 和 10 个 `features/*/feature.md` 已在后端 P0 完成后依据真实路由、schema、SSE 与权限边界重新生成。

当前处理规则：

1. 用户确认前，不创建 React 工程、不安装前端依赖、不实现页面。
2. 用户确认后，以这些新文档作为 React 实现基线。
3. 若当前代码与文档发生冲突，先报告并修订规范，不能静默选择其中一个。

## 4. 已确认且不可自行改变的决策

### 4.1 React 唯一 RAG / Agent 问答入口

React 只接入：

```text
POST /rag/chat/stream/events
```

以下接口是后端开发、测试、评估或兼容入口，不接入 React 问答 UI：

```text
POST /rag/chat
POST /rag/chat/stream
POST /rag/search
POST /rag/search/stream
POST /nl2sql/query
```

因此，会话持久化一致性只需围绕 `/rag/chat/stream/events` 的实际 provider 行为建立前端契约；不能因为其他 RAG 接口行为不同而扩大前端接入范围。

### 4.2 文档访问语义

不采用 `department / selected` 两种访问模式。

统一规则是：

1. 用户可以访问自己所属部门的全部部门文档。
2. 用户访问其他部门文档时，由目标文档所属部门主管或管理员按 `doc_id` 单独授权。
3. 跨部门授权不改变用户部门，不授予目标部门的其他文档，也不授予写、删、审批权限。
4. grant 必须记录授权人、被授权人、文档、时间和撤销事实。
5. 文档列表、详情、预览、下载、ES、Milvus 和 Markdown 父块扩展必须复用一致权限语义。

当前默认按“主管直接为精确账号授权/撤销”实现，不包含员工申请—主管审批工作流。除非用户后续明确要求，不新增审批状态机。

### 4.3 用户管理语义

账号类型：

```text
admin
department_manager
employee
```

- 管理员管理全平台。
- 部门主管只能创建、查看和管理自己主部门的普通员工。
- 部门主管不能创建管理员、其他主管或其他部门账号。
- 跨部门文档主管只管理自己部门文档的 grant，不能因此修改外部门用户的账号或 Tool 权限。
- 普通员工不能访问管理 interface。

### 4.4 实施边界

- 先完成后端 P0，再重新生成前端文档，最后才开始 React。
- 不增加前端文档上传入口。
- 权限范围只由服务端生成；前端不得提交 `allowed_departments`、`allowed_users` 扩权。
- `pipeline.stream()` 和 `/rag/chat/stream` 保持 legacy token-only，不承载新前端事件。

## 5. 已验证的当前后端事实

### 5.1 已有，可复用

- `src/fast_app/api/auth_routes.py`：login、refresh、me、API Key。
- `src/fast_app/api/rag_chat_routes.py`：`/rag/chat/stream/events` 结构化 SSE 主线。
- `src/fast_app/api/agent_task_plan_routes.py`：单计划读取、Markdown、confirm、confirm stream、cancel、retry。
- `src/fast_app/api/nl2sql_routes.py`：授权 Dataset 列表。
- `src/fast_app/core/exception_handlers.py` 与 `error_responses.py`：统一结构化错误、request_id、trace_id。
- `src/fast_app/services/conversation/conversation_repository.py`：已有 PostgreSQL Conversation/Message 查询与保存基础。
- `src/fast_app/db/gitlab_tables.py`：已有 `GitLabDocumentTable` 文档事实表。
- `src/fast_app/db/auth_tables.py`：已有 users、departments、roles、permissions、全局/部门角色绑定。

### 5.2 已确认缺口

- 已有 `department_manager` 部门作用域角色和账号类型推导，用户管理七个读写接口均已实现。
- 已有 capability interface；后续管理接口必须复用相同身份策略执行真实授权。
- 已有 logout 和 change-password；管理员 reset-password 随用户管理阶段实现。
- 用户管理目录、列表、详情、创建、完整 access 替换、状态和重置密码路由已完成。
- 已有跨部门 `doc_id` grant 事实表，但授权 interface、共享读取策略和检索下推尚未实现。
- 没有面向用户的 GitLab 文档列表、详情、预览、下载 interface。
- 没有会话 CRUD 和历史消息路由。
- 没有当前用户 TaskPlan 列表。
- `/rag/chat/stream/events` 和 `RagSource` 仍需固定前端 contract。

## 6. 脏工作树保护

后端仓库在本任务开始前已经存在大量用户改动，主要涉及 Office/Vision ingestion、GitLab 同步、配置和测试。它们不属于本接口任务，必须保留。

特别注意：

- `src/fast_app/dependencies/rag_dependencies.py` 已有用户改动，而后续 DI 可能需要它。修改前必须先读 `git diff -- <file>`，尽量通过新 route/module 复用现有 `get_db_session`，避免不必要重写。
- `src/fast_app/core/config.py`、`requirements.txt`、`src/fast_app/domain/knowledge_models.py`、`src/fast_app/api/knowledge_import_routes.py` 也有用户改动；除非当前 Todo 的最小实现确实需要，否则不要修改。
- 不得使用 `git reset --hard`、`git checkout --` 或清理未跟踪文件。
- 验证时使用目标文件 diff；不要把无关工作树噪声误报为本任务失败。

压缩后必须重新运行：

```powershell
git status --short
```

不要依赖本文中的工作树快照判断最新状态。

## 7. 压缩后第一个工作批次

当前进度（2026-08-24）：全部后端 P0 已完成；共享 Document Access Policy 已统一页面、下载、RAG、TaskPlan、ES、Milvus 和父块检索。React 总规范、架构规范和 10 个 feature 规范已重新生成，下一步等待用户确认；不要重复后端 interface 或提前开始 React 编码。

不要一次实现全部 28 项。第一个批次只建立后续管理接口依赖的身份和授权事实基础。

### 7.1 先读取

```text
alembic/versions/20260704_0005_create_agent_tool_permission_tables.py
alembic/versions/20260729_0010_remove_legacy_user_permissions.py
alembic/versions/20260815_0014_split_agent_task_plan_active_states.py
src/fast_app/db/auth_tables.py
src/fast_app/domain/auth_models.py
src/fast_app/domain/user_context.py
src/fast_app/domain/agent_tool_permissions.py
src/fast_app/schemas/auth_schema.py
src/fast_app/services/auth/auth_service.py
src/fast_app/services/auth/user_repository.py
src/fast_app/services/auth/permission_repository.py
src/fast_app/services/auth/permission_service.py
src/fast_app/api/auth_routes.py
src/fast_app/dependencies/rag_dependencies.py
scripts/tests/document_security/test_rbac_auth_migration.py
scripts/tests/agent_research/test_schema_field_descriptions.py
```

### 7.2 确认设计再编码

第一个批次应确认并实现最小事实模型：

1. `department_manager` 账号类型如何映射到服务器端角色。
2. 细粒度 Agent Tool/功能权限是否通过直接 user-permission binding 表达，避免为每种组合创建角色。
3. 跨部门 `document_access_grants` 表的 active/revoked、唯一性和审计字段。
4. `CurrentUserContext` 如何增加 `username`、`account_type`、部门作用域权限而不信任客户端。

任何新公共 Pydantic 字段都必须有 `Field(description=...)`，并扩展 schema description 回归。

### 7.3 第一个可交付切片

建议按以下小步执行：

1. 写迁移和 ORM/领域模型测试，建立 manager、直接权限和 document grant 事实。
2. 扩展 PermissionRepository/PermissionService，使有效权限兼容现有角色和新的直接授权。
3. 扩展 `/auth/me` 的可信身份字段。
4. 新增 `/auth/capabilities`。
5. 运行聚焦测试和 OpenAPI/schema 检查。
6. 只把真实完成的 Todo 项更新为 ✅；未完成项保持 ❌。

logout/change-password 已作为独立切片完成并通过数据库与 HTTP 契约验证。

## 8. 验证与 Todo 更新规则

每完成一个切片，至少执行：

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -B -m pytest scripts/tests/document_security/test_rbac_auth_migration.py -q
.\.venv\Scripts\python.exe -B -m pytest scripts/tests/agent_research/test_schema_field_descriptions.py -q
.\.venv\Scripts\python.exe -B -m alembic heads
git diff --check -- <本次修改文件>
```

根据实际影响再增加 permission、RAG ACL、Milvus、ES、TaskPlan 或 HTTP contract 测试。不能声称未运行的测试通过。

Todo 更新必须同时完成：

1. 把对应标题的 `❌` 改成 `✅`。
2. 在“实施记录”写日期、修改文件和实际命令。
3. 更新末尾进度汇总数字。
4. 如果只完成底层依赖、路由契约仍未完成，不得提前标记 interface 为 ✅。

## 9. 后续阶段顺序

保持 `BACKEND_INTERFACE_TODO.md` 当前顺序：

1. 身份字段、capability、部门主管角色与授权事实表。
2. 用户管理和跨部门文档 grant。
3. 共享 Document Access Policy，并验证 ES/Milvus 与文档读取一致性。
4. 文档列表、详情、预览和下载。
5. 会话 CRUD、历史和 `/rag/chat/stream/events` 统一落库。
6. TaskPlan 列表。
7. SSE/RagSource contract 固化与完整回归。
8. 后端 P0 全部 ✅ 后，重新生成 `react-agent-frontend/docs/`。
9. 用户确认新前端规范后，才开始 React 实现。

## 10. 压缩后恢复用短指令

如果上下文摘要信息不足，直接执行以下恢复动作：

```text
进入 D:\AI_Agent_Project\AI_Python_Project\python-agent-study。
读取 AGENTS.md、learning-docs/教学讲解规范.md、
docs/REACT_FRONTEND_BACKEND_IMPLEMENTATION_HANDOFF.md、
docs/BACKEND_INTERFACE_TODO.md。
检查 git status 和目标 diff。
读取当前前端 SPEC、ARCHITECTURE 和目标 feature；确认用户已经批准后才开始实现。
TodoList 当前无 ❌ P0 项；若出现新缺口，先补充 Todo 上下文再编码。
```

## 11. 本交接完成时的验证事实

- TodoList 位于后端 `docs/BACKEND_INTERFACE_TODO.md`。
- 前端 TodoList 副本不存在。
- 后端 P0 28/28 已完成。
- 当前未创建 React 源码、package.json 或依赖。
- 前端现有规范已按真实后端契约重新生成，等待用户确认。

## 12. 2026-08-24 手动压缩前的最新工作区快照

本节记录上一次手动压缩前的历史快照，已由第 13 节取代；恢复时以第 13 节和 `BACKEND_INTERFACE_TODO.md` 的实时状态为准。

### 12.1 Git 与数据库基线

- 后端仓库当前本地 `HEAD` 与 `origin/master` 均为 `9d697ca6973cd32b472f0e13c8fb89c0a66cda4b`，提交说明为“补充多模态文档摄取与前后端接口规划”。
- 该提交是开始补接口前由用户要求创建并推送的干净基线。
- 本轮身份、能力和用户管理只读接口代码均未提交。压缩恢复后不得提交、重置、清理或覆盖这些改动，除非用户再次明确要求。
- 本地 PostgreSQL 的 Alembic 版本已在 `20260824_0015 (head)`；迁移 `20260824_0015_add_identity_authorization_facts.py` 已完成升级、降级再升级验证。

### 12.2 当前未提交文件

已修改：

```text
alembic/env.py
docs/BACKEND_INTERFACE_TODO.md
docs/REACT_FRONTEND_BACKEND_IMPLEMENTATION_HANDOFF.md
scripts/tests/agent_research/test_schema_field_descriptions.py
scripts/tests/document_security/test_rbac_auth_migration.py
src/fast_app/api/auth_routes.py
src/fast_app/db/__init__.py
src/fast_app/db/auth_tables.py
src/fast_app/domain/agent_tool_permissions.py
src/fast_app/domain/auth_models.py
src/fast_app/domain/user_context.py
src/fast_app/main.py
src/fast_app/schemas/auth_schema.py
src/fast_app/services/auth/auth_crypto.py
src/fast_app/services/auth/auth_service.py
src/fast_app/services/auth/permission_repository.py
src/fast_app/services/auth/permission_service.py
src/fast_app/services/auth/user_repository.py
src/fast_app/services/exceptions.py
```

新增且未跟踪：

```text
alembic/versions/20260824_0015_add_identity_authorization_facts.py
scripts/tests/document_security/test_auth_identity_capabilities.py
scripts/tests/document_security/test_auth_session_security.py
scripts/tests/document_security/test_user_administration_read.py
src/fast_app/api/user_admin_routes.py
src/fast_app/db/document_access_tables.py
src/fast_app/dependencies/user_admin_dependencies.py
src/fast_app/schemas/user_admin_schema.py
src/fast_app/services/auth/capability_service.py
src/fast_app/services/auth/user_administration_repository.py
src/fast_app/services/auth/user_administration_service.py
```

恢复时仍须先执行 `git status --short`，因为以上列表只代表压缩前瞬间状态。

### 12.3 已完成并验证的接口

身份与能力分组 4/4：

- `GET /auth/me`：返回 `username`、服务器推导的 `account_type` 和部门作用域权限。
- `GET /auth/capabilities`：返回前端功能开关及用户管理范围。
- `POST /auth/logout`：校验 refresh token 归属，支持同一用户的幂等登出。
- `POST /auth/change-password`：验证旧密码和密码强度，在同一事务中更新 Argon2 hash 并撤销全部 refresh token。

用户与功能权限管理分组 3/7：

- `GET /admin/access/catalog`。
- `GET /admin/users`，使用 `updated_at + user_id` keyset cursor，主管范围由服务端固定为本部门员工。
- `GET /admin/users/{user_id}`，返回账号、部门角色、直接权限和有效权限聚合结果。

已实际通过：迁移升级/降级、RBAC migration、identity/capabilities、session security、Agent Tool permission policy、user administration read、schema descriptions、相关 OpenAPI 路由检查、`compileall` 和目标 diff check。

验证边界：当前虚拟环境没有安装 `ruff`；`alembic check` 仍会报告由 LangGraph 外部创建且未进入本项目 ORM metadata 的既有表差异，这不是本迁移产生的失败。

### 12.4 压缩后的准确恢复顺序

1. 读取仓库根 `AGENTS.md`。
2. 读取 `learning-docs/教学讲解规范.md`。
3. 完整读取本文和 `docs/BACKEND_INTERFACE_TODO.md`。
4. 执行 `git status --short`、`git diff --stat`，并检查用户管理相关目标 diff。
5. 不重复实现或重新设计第 12.3 节已经完成的 7 个接口。
6. 从 TodoList 中用户管理分组剩余的第一个 `❌` 接口继续。

### 12.5 下一切片：四个用户管理写接口

只实现以下四项，完成前不要进入跨部门文档授权接口：

1. `POST /admin/users`。
2. `PUT /admin/users/{user_id}/access`。
3. `PATCH /admin/users/{user_id}/status`。
4. `POST /admin/users/{user_id}/reset-password`。

实现顺序：

1. 新增独立的 `0016` 审计迁移，保留已经应用和验证过的 `0015` 不再改写。
2. 定义四个命令的 request/response schema，并为所有公共字段补 `Field(description=...)`。
3. 在现有 `UserAdministrationRepository` 中加入不自行提交的原子写方法。
4. 在 `UserAdministrationService` 集中完成范围、角色、权限和状态策略，路由保持薄层。
5. 每个写操作在同一数据库事务内写业务事实和统一审计事实。
6. 覆盖成功、403 越权、404、409 并发/重复、自我保护、最后一个管理员保护、事务回滚和密码安全测试。

必须坚持的业务边界：账号类型由服务端角色推导；部门主管只能管理本部门普通员工；跨部门文档访问只能由文档所属部门主管或系统管理员对精确 `doc_id` 授权；前端最终只接入 `/rag/chat/stream/events`；后端 P0 未全部完成前不得重新生成前端规范或开始 React 编码。

## 13. 用户管理写接口切片完成后的最新状态

### 13.1 Git 基线与工作区

- 上一切片已经提交并推送：`bcded1f1b107b6b8b7313ccda29a5a72377352f3`，提交说明“补齐身份能力与用户管理只读接口”。
- 本节描述的用户管理写接口改动尚未提交；恢复时先执行 `git status --short`，不得重置或清理。
- 本地数据库当前为 `20260824_0016 (head)`。

### 13.2 本切片完成内容

- `POST /admin/users`。
- `PUT /admin/users/{user_id}/access`。
- `PATCH /admin/users/{user_id}/status`。
- `POST /admin/users/{user_id}/reset-password`。
- `20260824_0016_add_user_administration_audits.py`：统一成功写操作审计事实，只保存安全前后快照。

完整访问快照使用 `department_access[]` 表达多部门成员关系、唯一主部门和各部门角色。部门主管只能管理仅属于自己主部门的 employee；多部门账号交由管理员，避免主管覆盖其他部门授权。禁用和重置密码都撤销 active refresh token 与 API Key，重新启用不恢复凭证。自操作和最后一个 active 系统管理员均有 409 保护。

### 13.3 已执行验证

- `test_user_administration_write.py`：真实 PostgreSQL 事务、三类账号、403、409、回滚、权限替换、凭证失效、密码和审计安全、HTTP/OpenAPI 契约通过。
- `test_rbac_auth_migration.py`、`test_user_administration_read.py`、`test_auth_identity_capabilities.py`、`test_auth_session_security.py`、`test_agent_tool_permission_policy.py` 通过。
- `test_schema_field_descriptions.py`、主应用写路由 OpenAPI 检查和 `compileall` 通过。
- 0016 downgrade 到 0015 后再 upgrade head 往返通过，当前仍在 0016 head。

### 13.4 下一准确切片

按 `BACKEND_INTERFACE_TODO.md` 顺序继续：

1. `GET /admin/document-access/grants`。
2. `POST /admin/document-access/grants`。
3. `DELETE /admin/document-access/grants/{grant_id}`。
4. 共享 Document Access Policy，并将相同语义用于文档读取、ES、Milvus 和 Markdown 父块扩展。

开始前读取 `DocumentAccessGrantTable`、`GitLabDocumentTable`、现有知识 ACL 策略、ES/Milvus filter 构建和父块扩展真实调用链。先实现 grant 管理深模块和测试，再接共享读取策略；不得只做路由而提前标记 Document Access Policy 为 ✅。

## 14. 2026-08-24 跨部门文档授权切片交接

### 14.1 当前工作树

- 上一提交仍为已推送的 `bcded1f1b107b6b8b7313ccda29a5a72377352f3`。
- 第 13 节用户管理写接口，以及本节跨部门文档授权和共享检索策略均尚未提交；恢复时必须保留全部现有修改。
- 数据库仍为 `20260824_0016 (head)`，本切片复用 0015 已建立的 `document_access_grants`，没有新增迁移。

### 14.2 本切片完成内容

- `GET /admin/document-access/grants`：keyset 分页与 actor 文档部门范围。
- `POST /admin/document-access/grants`：精确 active 账号、批量原子校验、幂等 active grant、并发 409。
- `DELETE /admin/document-access/grants/{grant_id}`：行锁、所属部门主管边界和保留审计的幂等撤销。
- `DocumentAccessPolicy`：统一管理员、public、本部门、原始 `allowed_users` 和 active grant 的读取语义。
- `/rag/chat/stream/events`、普通/兼容 RAG 路由和 TaskPlan 恢复均从数据库重新建立授权 scope；ES、Milvus 和 Markdown 父块扩展收到精确 `doc_id` OR 条件。

### 14.3 已执行验证

- `test_document_access_grants.py`：真实 PostgreSQL grant 生命周期、主管/管理员范围、撤销即时生效、共享读取裁决、ES/Milvus/父块 filter 与 HTTP/OpenAPI 契约通过。
- `test_agent_task_tool_loop.py`、`test_agentic_research_orchestration.py`、`test_llm_document_management_task.py` 通过，确认 TaskPlan `_current_filters()` 改为异步数据库 scope 后无回归。
- `test_nl2sql_api_contract.py` 与 `test_department_rag_acl_acceptance.py --skip-db` 通过；后者的实时 HTTP 检查因未提供 base URL 明确跳过。
- `test_schema_field_descriptions.py` 与 `compileall` 通过。Transformers 的 PyTorch 缺失提示不影响这些测试。

### 14.4 下一准确切片

按实现顺序完成知识文档页面读取：

1. `GET /knowledge/documents`。
2. `GET /knowledge/documents/{doc_id}`。
3. `GET /knowledge/documents/{doc_id}/content`。
4. `GET /knowledge/documents/{doc_id}/download`。

先读取 `GitLabDocumentTable`、`GitLabSourceTable`、GitLab Repository/Client 的当前版本内容读取能力和现有稳定错误响应。列表必须在 SQL 层应用可信 ACL 并做 keyset 分页；已知 `doc_id` 的详情、内容和下载必须通过同一个 `DocumentAccessPolicy`，不可在路由中复制权限判断。下载需要安全文件名、正确媒体类型和不可执行的内容处置。四个接口和同一组真实 grant 数据通过后，才把 Todo 中 `Document Access Policy 与检索下推` 标为 ✅。

## 15. 2026-08-24 知识文档读取切片交接

### 15.1 本切片完成内容

- `GET /knowledge/documents`：SQL ACL、keyset 分页和 query/department/type 筛选。
- `GET /knowledge/documents/{doc_id}`：固定 manifest 元数据与隐藏式 404。
- `GET /knowledge/documents/{doc_id}/content`：固定 revision/blob、受限安全文本预览。
- `GET /knowledge/documents/{doc_id}/download`：相同 ACL 与 revision、净化下载 header。
- `Document Access Policy 与检索下推` 已完成页面读取侧验收并在 Todo 标为 ✅。

新增模块边界为 `knowledge_document_schema.py`、`knowledge_document_read_repository.py`、`knowledge_document_read_service.py`、`document_content_gateway.py`、依赖和薄路由。GitLab 内容读取只使用 `sync_token_env`，不会把 token、base URL 或客户端可控 path/ref 暴露到接口。

### 15.2 已执行验证

- `test_knowledge_document_read.py`：真实 PostgreSQL 同部门/public/original ACL/active grant/隐藏文档、管理员全读、keyset、筛选、隐藏式 404、撤销即时生效、固定 revision/blob、超限、Markdown 与四类 Office/PDF 预览和下载 header 通过。
- `test_document_access_grants.py` 复跑通过。
- `test_user_administration_write.py`、`test_rbac_auth_migration.py` 复跑通过；数据库为 `20260824_0016 (head)`。
- Schema 字段说明、主应用四个知识文档路径 OpenAPI 和 `compileall` 通过。

### 15.3 下一准确切片

按 Todo 进入会话管理六项：

1. 读取 `conversation_repository.py`、`conversation_scope.py`、`rag_agent_pipeline_service.py` 与 `/rag/chat/stream/events` 的成功/error/abort/TaskPlan 事件链。
2. 定义 `GET/POST/PATCH/DELETE /conversations` 与 `GET /conversations/{conversation_id}/messages` 的当前用户隔离、keyset、软删除和消息 public schema。
3. 先完成会话 CRUD/历史 repository-service-router，再统一结构化流持久化；React 只接 `/rag/chat/stream/events`，不要为前端接其他 RAG 测试接口。
4. 当前前端主业务配置是 `rag_agent`；Classic 和普通 LangGraph 不是 Router 动态分支，不纳入本切片验收。必须明确 RagAgent 各意图分支何时落 user/assistant、sources、TaskPlan 和终态，以及 error/abort 是否保留部分结果。

## 16. 2026-08-24 会话管理切片交接

### 16.1 本切片完成内容

- `GET/POST/PATCH/DELETE /conversations` 与 `GET /conversations/{session_id}/messages` 已完成当前用户隔离、keyset 分页、标题管理、幂等硬删除和消息恢复。
- `20260824_0017_add_conversation_catalog_fields.py` 增加外部 session ID、标题和目录索引，并完成旧数据回填。
- `/rag/chat/stream/events` 使用 `StructuredConversationTurnRecorder` 统一保存当前 `rag_agent` turn；固定 turn ID、数据库冲突处理和 Memory Store 去重共同阻止重复消息。
- 完成、error、abort、TaskPlan、sources 与敏感 NL2SQL 直出均有明确持久化语义；RagAgent 原有内部保存点在该入口被关闭，避免双写。

### 16.2 已执行验证

- `test_conversation_management.py`：真实 PostgreSQL、用户隔离、CRUD、分页、排序、删除级联与 Memory 清理、完成/error/abort/TaskPlan/幂等 turn、HTTP/OpenAPI 通过。
- `test_conversation_message_order.py`、`test_nl2sql_api_contract.py`、`test_schema_field_descriptions.py` 通过。
- `test_agent_task_router.py`、`test_agent_router_clarification_flow.py` 通过，确认当前 `rag_agent` Router 意图与澄清分支；未把 Classic 或普通 LangGraph 当作动态 Router 状态。
- 0017 downgrade 到 0016 后再 upgrade head 往返通过，数据库恢复为 `20260824_0017 (head)`。

### 16.3 下一准确切片

会话切片完成后实现 `GET /agent/task-plans`；完成事实见第 17 节。

## 17. 2026-08-24 TaskPlan 列表切片交接

### 17.1 本切片完成内容

- `GET /agent/task-plans` 支持 `updated_at + task_plan_id` keyset、`status` 和 `session_id` 筛选，默认且始终只查询当前用户。
- `20260824_0018_add_task_plan_session_catalog.py` 新增会话关联和两条列表索引；RagAgent 创建计划时把可信 state 中的外部 session ID 写入计划和事实表。
- `AgentTaskPlanCatalogService` 只返回安全 SQL 投影，不反序列化或返回完整内部 snapshot、工具参数、租约、命令、RuntimeRecord 或 checkpoint。

### 17.2 已执行验证

- `test_agent_task_plan_list.py`：真实 PostgreSQL 用户隔离、同时间 keyset、status/session 筛选、摘要限制、公开字段防泄漏、HTTP 200/400/422 和 OpenAPI 通过。
- `test_agent_task_router.py` 验证 RagAgent 创建的文档 TaskPlan 绑定外部 session；`test_research_task_plan_v2.py` 与 Schema 字段说明通过。
- `test_rbac_auth_migration.py` 验证 0018 column/index；0018 downgrade 到 0017 后 upgrade head 往返通过，数据库恢复为 `20260824_0018 (head)`。

### 17.3 下一准确切片

完成剩余两项 P0：为 `/rag/chat/stream/events` 定义可生成 OpenAPI/fixture 的公开 SSE event schema、固定 request ID header 与终态顺序；随后给 `RagSource` 增加向后兼容的 `source_type` 和经过验证的 `href`。只验证当前 `rag_agent` 主业务事件，不运行 Classic、普通 LangGraph 或 Provider Matrix。

## 18. 2026-08-24 SSE 与来源契约切片交接

### 18.1 本切片完成内容

- `/rag/chat/stream/events` 每个 JSON payload 包含 `contract_version=1.0` 和 request ID；核心事件在 wire 输出前经过 Pydantic 校验，未知可选事件保持向前兼容。
- 正常流以唯一 `done` 结束，错误流以 `error` 结束；OpenAPI 声明 SSE 逻辑 frame 和 `X-Request-ID` header。
- `RagSource` 增加 `source_type`/`href`：知识文档用 doc ID，Web href 只接受无凭据 HTTP(S)；原始 metadata URL 不再公开。

### 18.2 已执行验证

- `test_rag_stream_contract.py`：当前 RagAgent 事件顺序、完成/error、必需字段、未知事件、request ID header/payload、知识/Web/恶意 URL 和 OpenAPI 通过。
- `test_agent_router_clarification_flow.py`、`test_nl2sql_api_contract.py`、`test_conversation_management.py`、`test_schema_field_descriptions.py` 通过。
- 本切片没有运行 Classic、普通 LangGraph 或 Provider Matrix。

### 18.3 下一准确切片

后端 P0 已全部完成。切换到 `react-agent-frontend`，重新读取真实后端 OpenAPI、`BACKEND_INTERFACE_TODO.md` 和本交接文档，删除旧规范中的未完成接口假设，然后重新生成 `docs/SPEC.md`、`docs/ARCHITECTURE.md` 和每个 `docs/features/<feature>/feature.md`。此步骤只整理规范，不开始 React 编码；规范经用户确认后再实施前端。

## 19. 2026-08-24 React 规范重新生成交接

### 19.1 已完成内容

- 保留并原位重写 `react-agent-frontend/docs/SPEC.md` 与 `docs/ARCHITECTURE.md`；两份 AGENTS.md 强制文档均存在，Git 状态为修改而非删除。
- 按真实后端路由、schema、SSE 契约与权限边界，重新生成 10 个 `docs/features/<feature>/feature.md`：身份认证、应用工作台、会话、RAG/Agent 对话、TaskPlan、知识文档、用户管理、跨部门文档授权、NL2SQL、Web 搜索。
- 扩展 `react-agent-frontend/AGENTS.md` 为工程实施规范，固化必读文档、实施门禁、唯一 SSE 入口、架构边界、认证与权限、安全、各 feature 不变量、测试和完成检查清单。
- React 对话仍只接入 `POST /rag/chat/stream/events`；不建立 Classic、普通 LangGraph 或 provider 选择器。
- 文档访问保持“同部门全部文档 + 外部门精确 doc ID grant”，不引入 department/selected 双模式。
- 当前 JSON token 契约下，前端规范选定 access token 仅内存、refresh token 仅当前标签页 `sessionStorage`；若后端未来改为 HttpOnly Cookie，再显式迁移。
- NL2SQL 历史恢复边界已写清：会话保存问题、摘要和终态，不承诺恢复完整结果表格。

### 19.2 已执行验证

- `AGENTS.md` 与 13 份前端规范文件全部存在，未发现 `待重新生成`、`等待后端` 或未完成接口假设。
- 前端文档 `git diff --name-status` 全部为 `M`，没有 `D`。
- `BACKEND_INTERFACE_TODO.md` 中 P0 为 28 个 ✅、0 个 ❌。
- 后端 Todo、交接文档和全部前端文档执行 `git diff --check` 通过；仅有 Windows LF/CRLF 提示。

### 19.3 下一准确切片

等待用户审阅并确认新的 `SPEC.md`、`ARCHITECTURE.md` 和 feature 规范。确认前不得创建 React 源码、`package.json` 或安装依赖；确认后再按文档从应用骨架、认证与共享 HTTP/SSE 基础设施开始实现。

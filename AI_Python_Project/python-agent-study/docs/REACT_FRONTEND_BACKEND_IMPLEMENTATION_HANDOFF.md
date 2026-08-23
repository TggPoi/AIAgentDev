# React 前端配套后端接口实施交接

## 1. 交接目的

本文件用于在手动上下文压缩后直接恢复 `python-agent-study` 后端接口补全工作。压缩后的会话不要重新规划 React，也不要先修改前端；应从本文和 `BACKEND_INTERFACE_TODO.md` 恢复后端实施状态。

生成时间：2026-08-24。

当前状态：身份与能力 4/4、用户与功能权限管理 3/7 已完成；用户管理只读目录、分页列表和详情已落地，下一切片实现四个管理写 interface。

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

TodoList 当前记录：

- 10 个已确认可复用的 ✅ interface。
- 21 个尚未完成的 ❌ interface/契约任务。
- 任何任务只有在实现、权限/失败路径测试、OpenAPI 或 SSE contract 核对、实施记录更新后才能改为 ✅。

### 3.2 前端文档当前不具备实施效力

`react-agent-frontend/docs/` 下现有 `SPEC.md`、`ARCHITECTURE.md` 和 `features/*/feature.md` 是在后端接口未完成时生成的设计草案。

当前处理规则：

1. 不用这些文件指导 React 编码。
2. 不创建 React 工程、不安装前端依赖、不实现页面。
3. 后端 P0 interface 全部完成并以真实 OpenAPI/SSE 契约验收后，重新读取后端代码并重新生成前端文档。
4. 重新生成时不得把现有草案直接标记为完成。

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

- 已有 `department_manager` 部门作用域角色和账号类型推导，但用户管理写接口尚未实现。
- 已有 capability interface；后续管理接口必须复用相同身份策略执行真实授权。
- 已有 logout 和 change-password；管理员 reset-password 随用户管理阶段实现。
- 没有用户管理路由和可下放权限目录。
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

当前进度（2026-08-24）：身份与能力 4/4、用户与功能权限管理 3/7 已完成。用户管理深模块已提供 catalog、keyset 用户列表和完整详情，主管范围固定在服务端。下一切片从 `POST /admin/users` 开始，继续实现 access 原子替换、状态切换和 reset-password；不要重复已完成只读 interface。

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
不要使用当前前端 docs 指导实现。
从 TodoList 当前第一个 ❌ 项继续；本交接第 7 节首个切片已经完成。
```

## 11. 本交接完成时的验证事实

- TodoList 位于后端 `docs/BACKEND_INTERFACE_TODO.md`。
- 前端 TodoList 副本不存在。
- 当前身份与能力分组 4/4 已完成，其余后端 interface 按 TodoList 状态继续。
- 当前未创建 React 源码、package.json 或依赖。
- 前端现有规范已明确为待后端完成后重新生成的草案。

## 12. 2026-08-24 手动压缩前的最新工作区快照

本节是本次手动上下文压缩后的首要恢复依据；若前文中的“第一个工作批次”与本节冲突，以本节和 `BACKEND_INTERFACE_TODO.md` 的实时状态为准。

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

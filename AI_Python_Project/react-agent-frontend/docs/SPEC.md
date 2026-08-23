# React RAG 工作台功能规格

> **状态：后端 P0 接口已完成，React 开发环境已经按用户指令搭建并验证。** 当前尚未开始任何业务模块；业务实现仍以本文和 feature 文档的后续确认范围为准。

## 1. 产品目标

本工程是 `python-agent-study` 企业 RAG / Agent 后端的 React 工作台。前端负责展示服务端已经授权的能力、发起请求、消费结构化事件并管理交互状态；认证、RBAC、部门边界、文档 ACL、Dataset Grant 和 TaskPlan 状态转换全部由后端裁决。

前端不得提交或自行推导 `allowed_departments`、`allowed_users`、显式文档授权集合等服务端权限事实。

## 2. 首期功能范围

首期包含十个功能模块：

1. 身份认证：登录、身份恢复、token 刷新、注销、修改密码。
2. 应用工作台：路由、导航、能力门控、统一异常与空状态。
3. 会话管理：会话列表、新建、重命名、删除、历史消息恢复。
4. RAG / Agent 对话：只接入 `POST /rag/chat/stream/events`。
5. TaskPlan：列表、详情、Markdown、确认、取消和重试。
6. 知识文档：列表、详情、提取内容预览和原文件下载。
7. 用户与功能权限：管理员和部门主管管理其权限范围内账号。
8. 跨部门文档授权：文档所属部门主管或管理员进行精确授权与撤销。
9. NL2SQL：Dataset 选择与统一对话流中的结构化查询结果。
10. Web 搜索：按能力和运行时开关展示，结果作为统一来源展示。

首期不包含文档上传、GitLab Source 配置与同步运维、RAG Eval、Debug Trace、LangSmith、API Key 管理页面，也不接入 `/rag/chat` 或 `/rag/chat/stream` 等开发/兼容接口。

## 3. 页面与路由

| 路由 | 页面 | 访问条件 |
| --- | --- | --- |
| `/login` | 登录 | 未登录 |
| `/chat`、`/chat/:sessionId` | 新对话、历史对话 | 已登录 |
| `/tasks`、`/tasks/:taskPlanId` | TaskPlan 列表与详情 | 已登录 |
| `/documents`、`/documents/:docId` | 文档列表、详情与预览 | `can_read_documents` |
| `/admin/users`、`/admin/users/:userId` | 用户管理 | `can_manage_users` |
| `/admin/document-grants` | 跨部门授权 | `can_manage_document_grants` |
| `/settings/security` | 修改密码与退出登录 | 已登录 |

前端能力判断只控制入口和交互提示。每个实际请求仍必须接受服务端重新鉴权，并处理 `401`、`403`、`404`、`409` 和 `422`。

## 4. 已完成的后端契约

### 4.1 身份与能力

- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `POST /auth/change-password`
- `GET /auth/me`
- `GET /auth/capabilities`

### 4.2 用户与跨部门授权

- `GET /admin/access/catalog`
- `GET /admin/users`
- `GET /admin/users/{user_id}`
- `POST /admin/users`
- `PUT /admin/users/{user_id}/access`
- `PATCH /admin/users/{user_id}/status`
- `POST /admin/users/{user_id}/reset-password`
- `GET /admin/document-access/grants`
- `POST /admin/document-access/grants`
- `DELETE /admin/document-access/grants/{grant_id}`

### 4.3 对话、会话与任务

- `POST /rag/chat/stream/events`：React 唯一对话入口。
- `GET /conversations`
- `POST /conversations`
- `PATCH /conversations/{session_id}`
- `DELETE /conversations/{session_id}`
- `GET /conversations/{session_id}/messages`
- `GET /agent/task-plans`
- `GET /agent/task-plans/{task_plan_id}`
- `GET /agent/task-plans/{task_plan_id}/markdown`
- `POST /agent/task-plans/{task_plan_id}/confirm`
- `POST /agent/task-plans/{task_plan_id}/confirm/stream`
- `POST /agent/task-plans/{task_plan_id}/cancel`
- `POST /agent/task-plans/{task_plan_id}/retry`

### 4.4 文档与数据集

- `GET /knowledge/documents`
- `GET /knowledge/documents/{doc_id}`
- `GET /knowledge/documents/{doc_id}/content`
- `GET /knowledge/documents/{doc_id}/download`
- `GET /nl2sql/datasets`

## 5. 核心业务规则

### 5.1 账号与部门

账号类型为 `admin`、`department_manager` 或 `employee`。管理员可管理全平台；部门主管只管理自己的主部门，不能创建管理员，也不能越权分配部门或权限。前端必须从 `/admin/access/catalog` 获取可选项，不能硬编码角色和权限全集。

### 5.2 文档访问

用户可读取其所属部门的全部文档。读取其他部门文档时，需要文档所属部门主管或管理员对具体 `doc_id` 单独授权。授权撤销立即影响文档读取和检索，不需要重新摄取知识库。

无权读取的文档详情、内容和下载统一按资源不可见处理；前端不能借助错误差异探测文档是否存在。

### 5.3 对话主链路

当前运行 provider 是 `rag_agent`。React 不显示 provider 选择器，也不分别调用 Classic 或普通 LangGraph 链路。Agent Router 在后端内部按意图进入知识问答、Web、NL2SQL、澄清或 TaskPlan 等状态。

每次请求使用客户端生成的外部 `session_id`。服务端会按当前用户隔离会话，并将结构化流的用户消息、回答、来源和关联 TaskPlan 持久化。

### 5.4 SSE 契约

每个 `data` JSON 都包含：

- `contract_version: "1.0"`
- `request_id: string`

正常完成以 `done` 为唯一成功终止事件；失败以 `error` 终止，不再追加 `done`。网络中断属于客户端未知结果，前端应停止本地流状态并重新读取会话，而不是自动重复提交。

前端需要识别核心事件、保留未知事件用于时间线兼容，并按 `request_id` 隔离并发或迟到事件。

### 5.5 来源跳转

统一来源对象通过 `source_type` 区分：

- `knowledge_document`：使用 `doc_id` 打开站内文档详情，`href` 为空。
- `web`：使用后端返回的、已净化的 HTTP(S) `href` 在新标签页打开。

浏览器不得从任意 metadata 字段拼接外链。

## 6. 通用交互与安全要求

- access token 只保存在内存；当前后端以 JSON 返回 refresh token，首期只将 refresh token 放在 `sessionStorage` 以支持当前标签页刷新恢复，不写入 `localStorage`、日志、URL 或分析事件。未来若后端改为 HttpOnly Cookie，再迁移存储方案。
- `401` 只触发一次共享 refresh；刷新失败则清空身份并跳转登录。
- `403` 表示当前身份无权执行；`404` 也可能是服务端刻意隐藏资源；`409` 表示状态冲突，应刷新服务端状态；`422` 映射到字段错误。
- 下载必须使用认证请求获取 Blob，不直接把受保护 URL 交给浏览器导航。
- 所有用户输入按纯文本处理；Markdown 渲染必须净化 HTML；Web 外链使用 `noopener,noreferrer`。
- 删除、禁用、重置密码、撤销授权、确认/取消 TaskPlan 等操作必须有明确确认和提交中状态。

## 7. 验收边界

开始 React 编码前，用户需要确认本文、`ARCHITECTURE.md` 和 `docs/features/*/feature.md`。实现完成时至少验证：路由保护、token 轮换并发、SSE 分片解析、终止状态、会话恢复、能力隐藏与服务端拒绝、文档不可枚举、TaskPlan 状态冲突和受保护下载。

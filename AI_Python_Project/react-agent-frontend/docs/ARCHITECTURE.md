# React RAG 工作台架构

> **状态：后端 P0 契约已完成，本文是 React 实现前的架构确认基线。**

## 1. 技术选型

- React + TypeScript + Vite。
- React Router：页面路由和登录保护。
- TanStack Query：普通 HTTP 查询、缓存、失效和 mutation 状态。
- 原生 `fetch` + `ReadableStream`：POST SSE；不使用只支持 GET 的 `EventSource`。
- Feature 本地 reducer：对话流、TaskPlan 流等有序事件状态。
- Vitest + React Testing Library + MSW：单元、组件和网络契约测试。

这些是首期实现约束，不引入全局状态框架、UI 插件系统或 provider 抽象。

## 2. 目标目录

```text
src/
├─ app/                 # Router、Provider、启动流程和顶层错误边界
├─ api/                 # HTTP client、认证轮换、SSE parser、共享错误模型
├─ components/          # 无业务归属的可复用组件
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
├─ layouts/             # 登录布局、工作台布局
├─ pages/               # 路由装配层，不承载协议细节
├─ test/                # MSW、fixtures、render helpers
└─ types/               # 真正跨 feature 的稳定类型
```

Feature 内部按 `api`、`components`、`hooks`、`model`、`pages` 组织；只有出现真实职责时才拆文件。

## 3. 状态归属

| 状态 | 所有者 | 原因 |
| --- | --- | --- |
| 当前用户、能力、access token | Auth Provider | 全应用共享且有启动/失效生命周期 |
| HTTP 服务端数据 | TanStack Query | 支持缓存、重新获取和 mutation 失效 |
| 当前 SSE 请求 | Chat/TaskPlan reducer | 事件有顺序、终止和取消语义 |
| 页面筛选与选中项 | URL search params / route params | 可刷新、可分享、浏览器前进后退一致 |
| 表单草稿 | 表单组件本地状态 | 不污染全局状态 |

服务端是会话、权限、文档授权和 TaskPlan 状态的最终事实源。前端缓存不参与授权判断。

## 4. 启动与认证

应用启动顺序：

1. 从当前标签页 `sessionStorage` 恢复 refresh token；access token 始终只在内存。
2. 必要时调用 `/auth/refresh` 获取新的 token pair。
3. 并行读取 `/auth/me` 与 `/auth/capabilities`。
4. 身份完成前显示启动屏，不短暂渲染受保护页面。
5. 恢复失败则清理本地身份并进入 `/login`。

HTTP client 注入 `Authorization: Bearer`。并发请求同时收到 `401` 时，只允许一个 refresh Promise；其他请求等待同一结果后各重放一次。刷新请求本身、登录和注销不进入递归重试。

## 5. HTTP 边界

`api/http-client.ts` 负责：

- 基础 URL、Authorization、`Content-Type` 和 `X-Request-ID` 关联。
- 解析统一错误体并映射为 `ApiError`。
- token 单飞刷新和一次性重放。
- JSON、空响应和 Blob 三类响应。
- 支持 AbortSignal。

Feature API 只暴露业务函数与 schema 类型。页面不得直接散落 URL、状态码分支或 token 处理。

Mutation 成功后精确失效相关 query，例如重命名会话后失效 conversation list/detail，撤销授权后失效 grants 与可见文档列表。

## 6. SSE 边界

结构化对话流由独立 parser 处理任意网络分片：累积 buffer，按空行识别 frame，合并多个 `data:` 行，忽略注释行，解析 `event` 与 JSON `data`。

流处理层必须：

- 校验 `contract_version === "1.0"` 和非空 `request_id`。
- 将核心事件送入强类型 reducer。
- 将未知事件作为只读时间线项保留，不让整个流失败。
- 只接受当前请求的事件；忽略被取消请求的迟到数据。
- `done` 转为 completed，`error` 转为 failed，EOF 且无终止事件转为 interrupted。
- 用户取消仅中止浏览器读取，不宣称服务端任务已经取消。

`POST /rag/chat/stream/events` 是唯一聊天入口；架构中不建立 Classic/LangGraph provider 切换层。

## 7. Feature 边界与接口映射

| Feature | 普通 HTTP | 流式接口 |
| --- | --- | --- |
| Auth | `/auth/*` | 无 |
| Conversations | `/conversations*` | 消息由聊天流写入 |
| Chat | 无独立非流式调用 | `/rag/chat/stream/events` |
| TaskPlan | `/agent/task-plans*` | `/{id}/confirm/stream` |
| Documents | `/knowledge/documents*` | 无 |
| Users | `/admin/access/catalog`、`/admin/users*` | 无 |
| Grants | `/admin/document-access/grants*` | 无 |
| NL2SQL | `/nl2sql/datasets` | 复用聊天流 |
| Web | `/auth/capabilities` | 复用聊天流 |

## 8. 路由和能力门控

认证路由保护与 capability 门控分离：未登录统一跳转登录；已登录但无能力的页面显示 403 页面并返回安全入口。导航根据 capabilities 隐藏入口，但路由组件仍要校验，服务端仍会再次鉴权。

账号权限变更后，相关 mutation 立即刷新 `/auth/me`、`/auth/capabilities` 或目标用户缓存。若当前用户被禁用或 refresh 被撤销，下一次认证失败即退出。

## 9. 安全约束

- 不记录 token、密码、查询敏感结果或原始错误响应中的秘密。
- 不从 JWT claim 或前端选项推导文档 ACL。
- Markdown 经过安全渲染，禁止未净化 HTML 和脚本 URL。
- 外链只接受后端 `RagSource.href`，并再次校验 HTTP(S)。
- 文档下载通过认证 fetch 后创建短生命周期 object URL，用毕 revoke。
- `404` 页面不区分资源不存在和无权访问。
- destructive mutation 禁止乐观更新；以服务端成功响应为准。

## 10. 测试分层

1. 纯函数：SSE parser、event reducer、游标参数、错误映射、URL 校验。
2. Feature 组件：加载、空、失败、权限、冲突、提交中和取消状态。
3. MSW 集成：登录恢复、401 单飞刷新、会话恢复、聊天终止、TaskPlan 控制、下载。
4. 关键浏览器流程：登录到对话、恢复历史、文档阅读、主管授权、管理员用户管理。

不使用真实模型输出作为前端自动化测试前提；使用固定事件序列验证协议和交互。

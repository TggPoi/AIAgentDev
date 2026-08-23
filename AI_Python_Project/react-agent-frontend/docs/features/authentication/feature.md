# 身份认证 Feature

## 1. 目标与边界

让已由管理员或部门主管创建的用户安全登录、恢复身份、轮换凭证、修改自己的密码并注销。系统不提供自助注册、找回密码或 API Key 管理页面。

## 2. 页面与交互

- `/login`：提交 `username_or_email` 与 `password`，成功后返回原受保护路由或进入 `/chat`。
- `/settings/security`：修改当前密码；成功后提示其他长期会话已失效，并执行本地退出。
- 用户菜单：显示身份摘要和注销操作。
- 应用启动：身份未决时显示启动屏，不先渲染受保护内容。

## 3. 后端契约

| 接口 | 请求 | 成功响应 |
| --- | --- | --- |
| `POST /auth/login` | `username_or_email`、`password` | access/refresh token pair、`expires_in` |
| `POST /auth/refresh` | `refresh_token` | 轮换后的 token pair |
| `POST /auth/logout` | `refresh_token` + Bearer | `logged_out`，重复注销安全 |
| `POST /auth/change-password` | `current_password`、`new_password` | `password_changed`、撤销的 refresh 数量 |
| `GET /auth/me` | Bearer | 用户、账号类型、部门、角色与有效权限快照 |
| `GET /auth/capabilities` | Bearer | 页面入口所需能力布尔值与管理范围 |

`/auth/me` 的主要字段是 `user_id`、`username`、`email`、`display_name`、`account_type`、`department_codes`、`primary_department_code`、全局角色/权限和部门权限。Capabilities 包含 `can_manage_users`、`user_management_scope`、`can_manage_document_grants`、`can_use_web_search`、`can_use_nl2sql`、`can_read_documents`、`can_manage_documents`。

## 4. 前端模型与数据流

```text
bootstrapping -> anonymous | authenticated
authenticated -> refreshing -> authenticated | anonymous
authenticated -> changingPassword -> anonymous
authenticated -> loggingOut -> anonymous
```

Auth Provider 持有内存中的 access token、当前用户和 capabilities。HTTP client 负责 Bearer 注入；多个请求同时 `401` 时共享一个 refresh Promise，成功后每个原请求只重放一次。登录、refresh、logout 本身不进入递归重试。

前端不得通过解码 JWT 代替 `/auth/me`，也不得根据 permission code 自行重算 capabilities。

## 5. 安全与失败处理

- 密码、access token、refresh token 不进入日志、URL、错误详情或埋点。
- 登录失败使用服务端通用错误，不区分用户名是否存在。
- refresh 失败时清空 Auth 状态与所有用户相关 Query Cache，再跳转 `/login`。
- 修改密码成功会撤销 active refresh token；当前页面不能继续假定会话有效。
- `422` 字段错误显示在对应输入框；网络失败保留账号字段但清空密码。
- 当前 JSON token 契约下，refresh token 只保存在当前标签页 `sessionStorage`，access token 只在内存；不使用 `localStorage`。若后端未来提供 HttpOnly Cookie，再通过明确迁移替换此方案。

## 6. 验收测试

1. 用户名和邮箱两种登录方式均可进入系统。
2. 启动恢复期间不会闪现受保护页面。
3. 并发 `401` 只产生一次 refresh，且原请求最多重放一次。
4. refresh 或账号状态失效后全应用退出并清空私有缓存。
5. 注销后旧 refresh token 无法换取新 token。
6. 修改密码校验错误可定位到字段，成功后要求重新登录。
7. 前端无注册、忘记密码和 API Key 管理入口。

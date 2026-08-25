# 身份认证 Feature

## 1. 目标与边界

让已由管理员或部门主管创建的用户安全登录、恢复身份、轮换凭证、修改自己的密码并注销。系统不提供自助注册、找回密码或 API Key 管理页面。

## 2. 页面与交互

- `/login`：提交 `username_or_email` 与 `password`，成功后只返回经过校验的站内相对 route；无效或缺失时进入 `/chat`。
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

AuthProvider 是认证事实的唯一前端所有者，持有 access token、refresh-token lifecycle、`CurrentUser`、`Capabilities`、`authStatus`、refresh coordination，以及 logout / identity-change lifecycle。`/auth/me` 与 `/auth/capabilities` 是 Authentication Bootstrap State，也是普通 TanStack Query Server-State 规则的明确例外：它们不进入 Query Cache，不允许再复制一份用户或能力真值。

Bootstrap 和 `reloadIdentitySnapshot()` 都并行请求 `/auth/me` 与 `/auth/capabilities`，只有两者成功且 user ID 未改变时才原子发布。Application Shell、Route Guard 和 Capability Guard 全部读取这个统一快照。可能影响当前登录用户权限的 mutation 完成后调用 `reloadIdentitySnapshot()`；只修改其他用户时失效对应业务 Query，不覆盖当前 AuthProvider。

HTTP client 负责 Bearer 注入；多个普通 HTTP 或尚未进入成功 stream 的请求同时 `401` 时共享一个 refresh Promise，成功后每个原请求只重放一次。登录、refresh、logout 和已经重放的请求本身不进入递归重试。Stream body 一旦开始读取，不再触发 replay。

前端不得通过解码 JWT 代替 `/auth/me`，也不得根据 permission code 自行重算 capabilities。

## 5. 安全与失败处理

- 密码、access token、refresh token 不进入日志、URL、错误详情或埋点。
- 登录失败使用服务端通用错误，不区分用户名是否存在。
- refresh 失败时清空 Auth 状态与所有用户相关 Query Cache，再跳转 `/login`。
- 修改密码成功会撤销 active refresh token；当前页面不能继续假定会话有效。
- `422` 字段错误显示在对应输入框；网络失败保留账号字段但清空密码。
- 当前 JSON token 契约下，refresh token 只保存在当前标签页 `sessionStorage`，access token 只在内存；不使用 `localStorage`。若后端未来提供 HttpOnly Cookie，再通过明确迁移替换此方案。
- Login return path 必须以单个 `/` 开头，并在当前应用 Origin 内解析；拒绝绝对 URL、其他 scheme / Origin、`//example.com` 和反斜杠变体。只把校验后的 pathname、search、hash 交给 React Router，绝不把原值传给 `window.location`；无效值回退 `/chat`。
- 当前 refresh token storage 是兼容 JSON Token Contract 的技术债务。目标形态是后端支持 `HttpOnly + Secure + appropriate SameSite` Cookie 后前后端共同迁移，React 不得单方面改为 Cookie。

## 6. 验收测试

1. 用户名和邮箱两种登录方式均可进入系统。
2. 启动恢复期间不会闪现受保护页面。
3. 并发 `401` 只产生一次 refresh，且原请求最多重放一次。
4. refresh 或账号状态失效后全应用退出并清空私有缓存。
5. 注销后旧 refresh token 无法换取新 token。
6. 修改密码校验错误可定位到字段，成功后要求重新登录。
7. 前端无注册、忘记密码和 API Key 管理入口。
8. `/auth/me` 与 `/auth/capabilities` 不存在 Query Cache 副本，identity reload 只原子发布完整快照。
9. 绝对 URL、protocol-relative URL 和其他 Origin 的 return path 均回退 `/chat`。

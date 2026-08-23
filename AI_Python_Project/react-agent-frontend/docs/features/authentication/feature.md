# 身份认证 Feature

## 1. 目标

让已由管理员创建的用户安全登录、恢复当前身份、轮换过期凭证并注销。系统不提供自助注册。

## 2. 当前后端现状

已存在登录、refresh 和当前用户接口；缺少前端 capability、服务端注销和修改密码接口。完整状态见后端工程 `python-agent-study/docs/BACKEND_INTERFACE_TODO.md`。

## 3. 页面与交互

- `/login`：用户名或邮箱、密码、提交状态和结构化错误。
- 应用启动时读取本地凭证，调用 `/auth/me` 与 `/auth/capabilities`。
- 登录成功跳转到用户原本请求的受保护页面，否则进入默认对话页。
- 不提供注册入口；忘记密码首期提示联系管理员。
- 用户菜单提供注销；注销完成后清空前端内存、缓存和凭证。

## 4. 前端 interface

```text
login(usernameOrEmail, password) -> TokenPair
restoreSession() -> AuthSnapshot | anonymous
refreshSession() -> TokenPair
logout() -> void
changePassword(currentPassword, newPassword) -> void
```

页面不直接调用 `fetch`，也不处理多个并发 refresh。身份 module 内部完成 Bearer Header、单飞 refresh 和错误归一化。

## 5. 状态模型

```text
bootstrapping -> anonymous
bootstrapping -> authenticated
authenticated -> refreshing -> authenticated
authenticated -> refreshing -> anonymous
authenticated -> anonymous (logout)
```

## 6. 信任与安全规则

- 前端不能从 JWT payload 自行推导最终权限；以 `/auth/me` 和 `/auth/capabilities` 为准。
- 密码和 token 不写日志、URL、埋点或错误详情。
- refresh 失败后不得循环重试。
- 被禁用用户的旧 refresh token 必须由后端拒绝。

## 7. 失败边界

- 401：凭证无效或过期；最多触发一次 refresh。
- 403：账号被禁用或当前操作不允许。
- 网络失败：保留登录表单内容但清空密码字段。
- 429：展示稍后重试，不自动连续登录。

## 8. 验收标准

1. 正确账号可以登录并恢复身份。
2. 错误密码不泄露“用户名存在与否”。
3. 并发 401 只发送一个 refresh 请求。
4. refresh 失败后所有受保护页面退出。
5. 注销后旧 refresh token 不能继续换取新 token。
6. 无注册入口，普通用户不能创建账号。

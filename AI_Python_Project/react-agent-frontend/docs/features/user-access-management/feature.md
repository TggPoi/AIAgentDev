# 用户与功能权限 Feature

## 1. 目标与角色边界

管理员管理全平台账号；部门主管只创建和管理自己主部门内的普通员工；员工没有用户管理能力。跨部门文档读取授权由独立 feature 处理。

| 账号类型 | 管理范围 |
| --- | --- |
| `admin` | 可管理全平台允许的账号、部门和权限 |
| `department_manager` | 仅自己主部门内的 employee |
| `employee` | 无管理范围 |

前端不复制这套规则作为授权器；以 `/auth/capabilities`、服务端裁剪后的 catalog 及每次 mutation 结果为准。

## 2. 后端契约

| 接口 | 说明 |
| --- | --- |
| `GET /admin/access/catalog` | 当前 actor 可选择的部门、账号类型、直接权限、部门角色 |
| `GET /admin/users` | `query`、`status`、`department_code`、`cursor`、`limit` |
| `GET /admin/users/{user_id}` | 目标账号完整访问快照 |
| `POST /admin/users` | 创建账号与初始访问快照，返回 201 |
| `PUT /admin/users/{user_id}/access` | 原子替换账号类型、部门、部门角色和直接权限 |
| `PATCH /admin/users/{user_id}/status` | `active|disabled`；禁用会撤销凭证 |
| `POST /admin/users/{user_id}/reset-password` | 设置新密码并撤销现有凭证 |

列表摘要包含账号类型、状态、部门、主部门与 `updated_at`。详情区分全局角色、直接权限、有效全局权限，以及各部门的成员关系、角色和有效权限。

## 3. 表单模型

创建表单提交 `username`、`password`、可选 `email/display_name`、`account_type`、`department_access[]`、`direct_permission_codes[]`。每个 department access 包含 `department_code`、`is_primary`、`role_codes`，整个快照必须且只能有一个主部门。

Access 编辑使用 PUT 完整快照，不做多个小 mutation。所有选择项按服务端 catalog 生成；catalog 变化后清理已不在允许集合中的草稿项，并要求用户重新确认，不能偷偷提交旧 code。

## 4. 页面与交互

- `/admin/users`：关键词、状态、部门筛选和游标分页。
- `/admin/users/:id`：基本信息、角色/权限来源、编辑 access、状态和密码重置。
- 创建与 access 编辑用分步或分组表单展示主部门约束及直接权限风险等级。
- 禁用、重置密码和改变账号类型需要二次确认；提交中锁定按钮。
- 密码仅存在于当前表单内，成功或失败后立即清空。

Mutation 不做乐观更新。成功后用响应替换 detail 并失效列表；如果后端允许且目标 `user_id` 恰为当前登录用户，还必须调用 AuthProvider 的 `reloadIdentitySnapshot()` 原子重取 `/auth/me` 与 `/auth/capabilities`，不能直接修改其中一个对象。禁用/重置响应展示被撤销的 refresh token/API Key 数量，但不展示凭证内容。

## 5. 失败与安全处理

- `409` 用户名/邮箱冲突或最后管理员/自操作保护：显示服务端稳定消息并刷新目标详情。
- `403/404`：actor 已失去管理范围时关闭编辑并返回列表。
- `422`：字段级错误映射到账号、主部门、角色或权限字段。
- 前端不能提供任意 code 输入框，也不能允许主管通过改请求构造其他部门。
- 所有写入由后端事务和审计保证；UI 不声称本地表单就是最终权限事实。

## 6. 验收测试

1. 管理员能按 catalog 创建三类账号并管理全平台范围。
2. 主管只能看到和创建自己主部门员工，不能分配不可下放项。
3. 普通员工没有入口且请求被后端拒绝。
4. access 更新要么完整成功，要么 UI 保留旧服务端快照。
5. 禁用和重置密码后旧 refresh/API Key 失效。
6. 自操作和最后管理员保护冲突能安全恢复页面状态。

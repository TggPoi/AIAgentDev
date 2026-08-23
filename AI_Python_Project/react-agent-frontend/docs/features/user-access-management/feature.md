# 用户与功能权限 Feature

## 1. 目标

让管理员管理全部账号，让部门主管创建和管理本部门普通员工，并在服务端允许范围内分配功能、Agent Tool 和部门文档操作权限。

跨部门文档读取授权不在本 feature 中处理，见 `../document-access-grants/feature.md`。

## 2. 账号类型

| 类型 | 管理范围 |
| --- | --- |
| `admin` | 全平台用户、部门和授权 |
| `department_manager` | 自己主部门的普通员工 |
| `employee` | 无用户管理能力 |

部门主管不能创建管理员、其他主管或其他部门账号，也不能修改管理员/主管账号。

## 3. 页面

- 用户分页列表：关键词、状态、部门筛选。
- 创建用户：用户名、邮箱、显示名、初始密码、账号类型、部门。
- 用户详情：基本信息、状态、角色、有效权限、直接授权。
- 权限编辑：使用服务端目录生成复选项，提交完整 access snapshot。
- 启用/禁用和重置密码：高风险操作二次确认。

## 4. 前端 interface

```text
getAccessCatalog() -> AccessCatalog
listManagedUsers(filters, cursor) -> Page<ManagedUser>
getManagedUser(id) -> ManagedUserDetail
createManagedUser(input) -> ManagedUserDetail
replaceUserAccess(id, snapshot) -> ManagedUserDetail
setUserStatus(id, status) -> ManagedUserDetail
resetUserPassword(id, newPassword) -> PasswordResetResult
```

`AccessCatalog` 由后端根据当前管理者裁剪。前端不能维护“哪些权限允许主管下放”的硬编码副本。

## 5. 后端实现要求

- 创建用户及角色、部门、直接权限写入必须在一个事务内完成。
- 更新 access 使用完整 snapshot 原子替换，避免多接口部分成功。
- 禁用用户后，认证层立即拒绝新请求，并按确定策略撤销 refresh token/API Key。
- 用户名和邮箱冲突返回稳定 409 code。
- 所有管理写操作记录 actor、target、变更前后摘要和 request ID。

## 6. 验收标准

1. 管理员能创建三类账号并在全平台管理。
2. 部门主管只能创建自己部门普通员工。
3. 部门主管不能把自己没有或不可下放的权限授予员工。
4. 普通员工无法访问任何管理接口。
5. access 更新失败时不留下部分角色或权限。
6. 禁用账号不能继续 refresh 或调用业务接口。

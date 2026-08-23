# 跨部门文档授权 Feature

## 1. 目标

当用户需要读取其他部门的一篇或多篇文档时，由目标文档所属部门主管或管理员创建精确到 `doc_id` 的授权，而不改变用户所属部门和其他功能权限。

## 2. 核心规则

1. 同部门文档不需要单篇授权。
2. 部门主管只能授权自己主管部门拥有的文档。
3. 管理员可以授权任意部门文档。
4. 被授权人可以来自其他部门。
5. grant 只提供读取能力，不提供修改、删除、审批或目标部门的其他文档访问权。
6. 撤销必须立即影响文档列表、详情、下载和 ES/Milvus 检索。

## 3. 授权事实

```text
DocumentAccessGrant
  id
  doc_id
  document_department_code
  grantee_user_id
  granted_by_user_id
  granted_at
  revoked_by_user_id
  revoked_at
  status
```

数据库必须防止同一用户、同一文档存在多个 active grant。

## 4. 页面流程

- 主管进入“跨部门授权”，只能看到自己部门文档的授权记录。
- 输入目标用户的精确用户名或用户 ID，并选择本部门文档。
- 页面展示将要授予的文档和目标用户，确认后提交。
- 已授权列表支持按用户、文档和状态过滤，并允许撤销。

首期不创建复杂申请/审批流；若后续需要员工主动申请，应作为独立 feature 扩展，不能把自然语言聊天当审批记录。

## 5. 前端 interface

```text
listDocumentGrants(filters, cursor) -> Page<DocumentAccessGrant>
grantDocumentAccess(targetAccount, documentIds) -> DocumentAccessGrant[]
revokeDocumentGrant(grantId) -> DocumentAccessGrant
```

目标账号使用精确标识提交，后端返回脱敏的确认信息；不为主管开放跨部门完整用户目录。

## 6. 后端实现要求

- 在事务内校验 actor 管理的部门、文档归属、目标用户状态和重复 grant。
- 读取权限将 active grant 的 `doc_id` 合并进服务端 RetrievalPermissionScope。
- ES 使用 `doc_id terms`，Milvus 使用 `doc_id in`，并与 public/department 条件做 OR。
- 记录创建和撤销审计，不物理删除历史 grant。

## 7. 验收标准

1. 开发部门主管能授权一篇开发文档给美术员工。
2. 该员工只能访问获准文档，不能访问其他开发文档。
3. 美术部门主管不能授权开发部门文档。
4. 撤销后文档页面和 RAG 召回同时失效。
5. 重复授权不会生成多个 active grant。

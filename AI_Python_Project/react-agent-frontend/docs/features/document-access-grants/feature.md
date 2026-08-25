# 跨部门文档授权 Feature

## 1. 目标与业务规则

由文档所属部门主管或管理员，将具体外部门文档的只读权限授予目标用户，而不改变用户部门、角色或其他权限。

Public 文档属于公共区域，所有已认证用户都可读取，不进入 grant 业务语义。对于非 public 文档，同部门读取不需要 grant；主管只能授权自己主管部门的文档；管理员可管理任意部门；被授权人可来自其他部门。Grant 不授予修改、删除、审批或该部门其他文档的权限，撤销后立即影响文档读取与 RAG 检索。

## 2. 后端契约

| 接口 | 说明 |
| --- | --- |
| `GET /admin/document-access/grants` | `target_account`、`doc_id`、`status`、`department_code`、`cursor`、`limit` |
| `POST /admin/document-access/grants` | 精确账号 + 1 到 100 个不重复 `document_ids` 的原子授权 |
| `DELETE /admin/document-access/grants/{grant_id}` | 幂等撤销并返回保留审计字段的记录 |

创建请求使用 `target_account`（精确用户名或邮箱）和 `document_ids`。响应返回 `items`、`created_count`、`existing_count`，因此重复提交已有 active grant 是幂等复用，不产生第二条 active 记录。

Grant 项包含 `grant_id`、`document_id`、`repository_path`、`document_department_code`、最小 `grantee` 摘要、`status`、授权/撤销 actor 与时间。

## 3. 页面流程

主管进入页面后，授权列表和可选非 public 文档都受其部门范围限制；管理员可使用部门筛选。创建流程输入精确用户名或邮箱，从知识文档列表选择一到多篇需要跨部门授权的非 public 文档，确认目标账号和文档清单后一次提交。

首期不提供跨部门完整用户搜索、不建立申请审批流，也不把聊天记录视为授权依据。目标账号不存在、未激活或不允许授权时，仅展示服务端安全错误。

列表可按账号文本、doc ID、状态和部门过滤。Active 项允许撤销；revoked 项只读展示审计时间，不能恢复，重新授权应发起新的创建请求。

## 4. 缓存与即时生效

创建或撤销成功后失效 grant 列表和相关知识文档 Query。若当前登录用户正是被授权人，下一次列表/详情/检索由后端实时 grant 决定；前端不缓存一份“允许 doc IDs”参与放行。

撤销不做乐观移除，避免 UI 先显示成功但服务端事务失败。`409`、`403`、`404` 后重新加载记录；对资源不可见原因不作推断。

## 5. 验收测试

1. 部门主管可把自己部门的一篇文档授予外部门员工。
2. 员工只获得目标文档，不能读取该外部门其他文档。
3. 其他部门主管不能授权不属于自己的文档。
4. 撤销后列表、详情、内容、下载和 ES/Milvus 检索同步失效。
5. 重复创建返回 existing count，不产生多个 active grant。
6. 撤销记录保留授权人、撤销人和时间，不从历史列表消失。
7. Public 文档对所有已认证用户可读，不要求也不创建冗余 grant。

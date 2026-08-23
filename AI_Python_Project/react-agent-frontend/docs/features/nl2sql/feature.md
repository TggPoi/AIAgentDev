# NL2SQL Feature

## 1. 目标

允许具备数据查询权限的用户在对话页选择已授权 Dataset，并继续通过统一的 RAG / Agent 结构化流完成问题、SQL 生成、只读执行和结果展示。

## 2. interface 边界

- Dataset 发现：`GET /nl2sql/datasets`。
- 执行：只使用 `POST /rag/chat/stream/events`。
- React 不调用 `POST /nl2sql/query`。

## 3. 页面交互

- capability 不允许 NL2SQL 时不显示 Dataset 控件。
- Dataset 下拉框只展示服务端返回的可用项。
- 未选择 Dataset：不提交 `dataset_id` 和 `nl2sql_action`。
- 选择 Dataset：显式提交 `dataset_id` 与 `nl2sql_action=query`。
- 结果区展示 SQL、列、行、数量、截断状态、执行时间、warnings 和中文总结。

## 4. 事件

- `nl2sql_sql_generated`：展示参数化 SQL 和生成尝试次数。
- `nl2sql_result`：展示结构化表格和总结。
- `error`：按稳定 NL2SQL error code 区分权限、禁用、不安全 SQL、执行失败。
- `done`：固化本轮状态。

## 5. 安全规则

- Dataset 授权由后端 RBAC/Grant 决定，前端提交 ID 不代表有权限。
- 前端不允许编辑并执行后端生成的 SQL。
- 敏感 Dataset 的显示必须服从后端脱敏和截断结果。
- 表格单元格作为文本渲染，不执行 HTML。

## 6. 验收标准

1. 无权限用户看不到 Dataset 控件，伪造 dataset ID 仍返回 403。
2. 未选 Dataset 的普通 RAG 问题不会进入 NL2SQL。
3. SQL、表格、总结和 warnings 能从结构化事件恢复。
4. 大结果遵守后端截断信息，页面不会无限渲染。
5. 网络记录中没有 `/nl2sql/query` 请求。

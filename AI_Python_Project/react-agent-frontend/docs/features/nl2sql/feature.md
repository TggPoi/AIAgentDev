# NL2SQL Feature

## 1. 目标与接口边界

允许具备数据权限的用户在对话页选择已授权 Dataset，并通过统一 RagAgent 结构化流完成 SQL 生成、只读执行和结果展示。

- Dataset 发现：`GET /nl2sql/datasets`。
- 执行：只使用 `POST /rag/chat/stream/events`。
- React 不调用开发接口 `POST /nl2sql/query`。

## 2. Dataset 与请求

仅当 `can_use_nl2sql=true` 时加载 Dataset。服务端返回 `dataset_id`、`name`、`domain`、`privacy_classification`、`report_supported`；列表已经按 RBAC、Dataset Grant、启用状态裁剪。

未选择 Dataset 时，请求中两个字段都省略。选择后必须同时提交 `dataset_id` 和 `nl2sql_action`。`query` 用于直接只读查询；只有 `report_supported=true` 才允许选择 `report`，其后续流程可能进入需确认的 TaskPlan。

前端不允许输入任意 Dataset ID，不把 capability 或列表命中视为最终授权；服务端会在每次请求重新校验。

## 3. 事件与结果

- `nl2sql_sql_generated`：展示 `query_id`、Dataset、参数化只读 SQL 和 `attempt_count`。
- `nl2sql_result`：展示 `columns`、`rows`、`row_count`、`truncated`、`execution_ms`、`summary`、`warnings` 和必要审计 ID。
- `error`：按稳定 code 展示权限、Dataset 禁用、不安全 SQL 或执行失败。
- `done`：正常终态；error 后不等待 done。

结果表使用列定义顺序，单元格全部作为文本；大表放在有界滚动容器，`truncated` 和 warnings 必须明显显示。SQL 只读展示，不提供编辑和执行按钮。

## 4. 隐私与恢复

敏感 Dataset 使用后端的本地标记化、RLS、脱敏和截断结果；前端不得把结果自动带入 Web 搜索、日志或分析事件。`privacy_classification` 用于提示，不改变前端执行路径。

NL2SQL turn 与普通对话一样由结构化流持久化。刷新后，conversation messages 能恢复用户问题、结果摘要与终止状态，但当前不会持久化完整表格；详细行列只存在于本次流的前端状态。报告类流程按关联 TaskPlan 恢复，禁止通过自动重新提交问题来“恢复”。

## 5. 验收测试

1. 无能力用户看不到 Dataset 控件，伪造 ID 仍被后端拒绝。
2. Dataset/action 的成对校验阻止半绑定请求。
3. 参数化 SQL、表格、总结、截断和 warnings 在当前结构化流执行期间正确构建和展示。
4. report 仅在服务端声明支持时可选，并正确进入 TaskPlan。
5. 敏感数据不进入 Web 请求、日志或 HTML 执行路径。
6. 网络记录中不存在 `/nl2sql/query`。
7. 页面刷新后只恢复后端实际持久化的问题、摘要与终止状态；完整结果表不会通过自动重新提交问题恢复。

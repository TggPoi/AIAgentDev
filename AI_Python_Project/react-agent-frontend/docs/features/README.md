# Feature 规范索引

> **状态：后端 P0 接口已完成，全部 feature 文档已按真实契约重新生成。** 文档经用户确认后才进入 React 编码。

| 功能模块 | 文档 | 后端状态 |
| --- | --- | --- |
| 身份认证 | `authentication/feature.md` | 可实现 |
| 应用工作台 | `application-shell/feature.md` | 可实现 |
| 会话管理 | `conversations/feature.md` | 可实现 |
| RAG / Agent 对话 | `rag-agent-chat/feature.md` | 可实现，唯一入口为结构化 SSE |
| TaskPlan | `task-plans/feature.md` | 可实现 |
| 知识文档 | `knowledge-documents/feature.md` | 可实现 |
| 用户与功能权限 | `user-access-management/feature.md` | 可实现 |
| 跨部门文档授权 | `document-access-grants/feature.md` | 可实现 |
| NL2SQL | `nl2sql/feature.md` | 可实现，复用统一对话流 |
| Web 搜索 | `web-search/feature.md` | 可实现，复用统一对话流 |

每个 `feature.md` 固定说明：目标与边界、页面与状态、后端契约、前端模型与数据流、权限和失败处理、验收测试。若后续 OpenAPI 或后端实现发生变化，先更新对应 feature 文档，再修改代码。

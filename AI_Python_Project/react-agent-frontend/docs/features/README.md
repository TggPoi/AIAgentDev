# Feature 规范索引

> **状态：全部 Feature 文档均为已批准的行为基线。** 本索引只负责 Feature 导航和后端能力边界；实际实施进度、checkpoint 与当前阻塞以 active Execution Plan、Git、Repository 与 Tests 为准。

| 功能模块 | 文档 | 后端状态 |
| --- | --- | --- |
| 身份认证 | `authentication/feature.md` | 可实现 |
| 应用工作台 | `application-shell/feature.md` | 可实现 |
| 会话管理 | `conversations/feature.md` | 可实现 |
| RAG / Agent 对话 | `rag-agent-chat/feature.md` | 可实现，唯一入口为结构化 SSE |
| TaskPlan | `task-plans/feature.md` | 可实现；首期确认只使用 confirm stream |
| 知识文档 | `knowledge-documents/feature.md` | 可实现；下载 revision/文件名响应头可跨域读取 |
| 用户与功能权限 | `user-access-management/feature.md` | 可实现 |
| 跨部门文档授权 | `document-access-grants/feature.md` | 可实现 |
| NL2SQL | `nl2sql/feature.md` | 可实现，复用统一对话流 |
| Web 搜索 | `web-search/feature.md` | 可实现，复用统一对话流 |

每个 `feature.md` 固定说明：目标与边界、页面与状态、后端契约、前端模型与数据流、权限和失败处理、验收测试。若后续 OpenAPI 或后端实现发生变化，先更新对应 feature 文档，再修改代码。

全局视觉方向由 `docs/SPEC.md` 唯一定义，各 Feature 默认继承；只有消息层级、TaskPlan 状态、Document Warning、NL2SQL 表格等局部语义色需要在 Feature 内补充，且不得改变蓝白主视觉。

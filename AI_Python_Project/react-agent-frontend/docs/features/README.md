# Feature 规范索引

> **状态：目录内全部 feature 文档待重新生成。** 后端 P0 interface 完成前，
> 这些文件仅用于保存需求拆分，不是 React 实现规范。

本目录按业务功能拆分 React 工作台规范。每个子目录只描述一个功能 module；后端接口是否已经完成，以后端工程 `python-agent-study/docs/BACKEND_INTERFACE_TODO.md` 为唯一状态来源。

| 功能 module | 文档 | 当前阶段 |
| --- | --- | --- |
| 身份认证 | `authentication/feature.md` | 规范完成，等待后端缺口 |
| 应用工作台 | `application-shell/feature.md` | 规范完成，等待后端 capability |
| 会话管理 | `conversations/feature.md` | 规范完成，等待后端接口 |
| RAG / Agent 对话 | `rag-agent-chat/feature.md` | 规范完成，等待事件契约固化 |
| TaskPlan | `task-plans/feature.md` | 规范完成，等待列表接口 |
| 知识文档 | `knowledge-documents/feature.md` | 规范完成，等待后端接口 |
| 用户与功能权限 | `user-access-management/feature.md` | 规范完成，等待后端接口 |
| 跨部门文档授权 | `document-access-grants/feature.md` | 规范完成，等待授权模型与接口 |
| NL2SQL | `nl2sql/feature.md` | 规范完成，复用统一对话流 |
| 联网搜索 | `web-search/feature.md` | 规范完成，复用统一对话流 |

## 文档维护规则

1. 行为变化先更新 `SPEC.md`，再更新对应 feature。
2. interface 字段或状态变化同时更新后端工程的 `python-agent-study/docs/BACKEND_INTERFACE_TODO.md`。
3. feature 文档不得把路线计划写成已实现事实。
4. 编码完成后只更新“当前阶段”和验收结果，不删除失败边界与安全约束。

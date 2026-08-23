# 应用工作台 Feature

## 1. 目标

提供蓝白色调的统一页面壳、侧边栏、顶栏、路由保护、全局错误反馈和 capability 驱动的菜单。

## 2. 布局

- 左侧：会话列表、新建会话、对话和文档入口。
- 顶栏：当前用户、所属部门、知识版本提示、用户菜单。
- 主区域：当前 feature 页面。
- 窄屏：侧边栏收起为抽屉，主交互仍可完整使用。

## 3. 导航规则

| 菜单 | 显示条件 |
| --- | --- |
| 对话 | 已登录 |
| 文档 | `can_read_documents` |
| 用户管理 | `can_manage_users` |
| 跨部门授权 | `can_manage_document_grants` |

NL2SQL 和联网搜索属于对话页能力，不创建平行问答页面。

## 4. 前端 interface

应用壳只读取：

```text
AuthSnapshot
FrontendCapabilities
ConversationListSummary
RouteDescriptor
```

它不读取 RBAC 原始表，也不根据 permission code 重新计算后端规则。

## 5. 通用页面状态

每个异步页面必须显式支持：

```text
loading
ready
empty
error
refreshing
```

全局 toast 只用于操作结果；会阻断当前工作的错误必须留在页面内，不得一闪而过。

## 6. 错误展示

- 用户信息：`message`。
- 排障信息：可复制 `request_id`，高级详情中显示 `trace_id` 和 `code`。
- 不展示服务器堆栈、Prompt、token 或 GitLab 内部凭证。

## 7. 验收标准

1. 无权限菜单不会出现，直接访问仍正确展示后端 403。
2. 页面刷新后身份和当前位置可以恢复。
3. 桌面与窄屏都能完成核心操作。
4. 所有后端错误都能定位到 request ID。

# 应用工作台 Feature

## 1. 目标

提供统一布局、路由保护、能力驱动导航和一致的加载、空、失败与操作反馈。应用壳只编排 feature，不承载 SSE、RBAC 或业务 mutation 细节。

## 2. 布局与路由

- 左侧：新建对话、会话列表、TaskPlan、知识文档及有权管理的后台入口。
- 顶栏：页面标题、当前用户、主部门、用户菜单。
- 主区域：当前 route 页面；阻断错误留在内容区。
- 窄屏：侧栏为可关闭抽屉，打开页面或选择会话后自动收起。

| 导航 | 条件 |
| --- | --- |
| 对话、TaskPlan、账号安全 | 已登录 |
| 知识文档 | `can_read_documents` |
| 用户管理 | `can_manage_users` |
| 跨部门授权 | `can_manage_document_grants` |

NL2SQL 和 Web 搜索属于对话能力，不建立平行问答页。无 provider 选择器。

## 3. 启动数据流

应用壳读取 Auth Provider 的 `CurrentUser` 与 `Capabilities`，并按需挂载会话列表 Query。启动流程完成前不计算导航；身份失败时只保留登录路由。

路由分三层：公共路由、authenticated guard、capability guard。隐藏菜单只是体验优化；用户直接访问受限 URL 时仍发起必要的服务端校验，并以 `403` 或隐藏式 `404` 结果为准。

## 4. 通用页面状态

每个异步页面显式区分 `loading`、`ready`、`empty`、`error`、`refreshing`。初次 loading 使用页面骨架；后台 refreshing 保留已有内容。Toast 只反馈非阻断 mutation 结果，不能替代页面错误。

统一错误视图展示安全的 `message`、`code` 与可复制 `request_id`；若响应包含 `trace_id`，只放在折叠的排障信息中。禁止展示堆栈、Prompt、token、SQL 凭证和 GitLab 凭证。

## 5. 一致性规则

- 登录用户变化时清空上一用户的所有 Query Cache 与进行中的流。
- capabilities 刷新后立即重算导航；当前 route 已失权时跳转安全入口并提示原因。
- 页面筛选写入 URL search params，选中实体写入 route params。
- 全局错误边界只处理渲染异常；请求异常由对应 feature 处理。
- 所有弹窗支持键盘操作、焦点回收和重复提交锁定。

## 6. 验收测试

1. 未登录访问任意受保护 URL 会携带安全 return path 跳转登录。
2. 无能力入口不显示，直接访问不会越过服务端授权。
3. 刷新浏览器可恢复身份、route 和 URL 筛选。
4. 桌面和窄屏均可完成对话、文档与管理操作。
5. 私有缓存不会跨用户残留。
6. 后端结构化错误可显示 request ID，敏感字段不会渲染。

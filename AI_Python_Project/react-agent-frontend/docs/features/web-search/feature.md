# 联网搜索 Feature

## 1. 目标与边界

允许具备 Web Search Tool 权限的用户在对话前决定是否允许联网，并在统一事件时间线和来源区查看结果。无独立 Web 页面或问答接口，只使用 `POST /rag/chat/stream/events`。

## 2. 能力与运行时条件

`GET /auth/capabilities` 的 `can_use_web_search` 决定是否显示控制；该值只代表权限存在，不保证外部 Provider 当前可用。后端运行时开关、Router、来源策略和 Tool permission 仍会在请求中裁决。

- 主控件“允许联网搜索”控制 `allow_direct_web`，首期默认关闭。
- 高级控件“本地证据不足时允许 Web 补充”控制 `allow_web_fallback`，首期默认关闭。
- 无能力：隐藏两个控件，并显式提交 `allow_direct_web=false`、`allow_web_fallback=false`。
- 有能力但主控件关闭：两个字段均为 `false`，高级控件禁用。
- 有能力且主控件开启：`allow_direct_web=true`，`allow_web_fallback` 等于高级控件当前值。

`allow_direct_web` 表示用户明确公开 Web 查询；`allow_web_fallback` 表示复杂研究在本地证据不足时允许外部补充。开启不代表一定调用。

两个设置按当前认证用户、当前标签页存入 `sessionStorage`，页面刷新后恢复；logout 或 identity change 时清除。前端始终显式发送两个字段，不能因后端默认值变化而改变产品语义。

## 3. 事件与来源

Web 工具进度使用 RagAgent 的任务/工具事件显示。未知新增事件遵守 Chat 的安全投影：只保留 event type、已验证 request ID、received time 和通用不支持状态，原始 payload 不展示、不记录、不缓存、不持久化。最终网页引用是 `RagSource`：`source_type=web`、标题、`href`、`content_preview` 和其他已确认安全摘要。

前端只读取后端显式 `href`，再次校验无用户名密码的 HTTP(S) URL；展示域名应从该 URL 安全解析。外链新标签使用 `noopener,noreferrer`。不能从 `metadata.url` 或任意 metadata key 拼接地址。

知识文档来源与网页来源使用不同图标和导航：文档走站内 `doc_id`，网页走 `href`。

## 4. 隐私与失败处理

首次开启或合适位置提示：公开问题可能发送到外部搜索服务。敏感 Dataset 结果、内部文档正文、ACL 与权限字段不得由前端组合进 Web query；后端安全边界仍是最终保障。

Web 工具失败显示结构化错误或任务事件，但不删除已经得到的本地来源与回答。用户可关闭联网后重新提问；前端不自动重试外部调用。

## 5. 验收测试

1. 无能力用户看不到开关，伪造开启仍被后端拒绝。
2. 两个 Web 开关的不同语义可明确控制并准确提交。
3. 开启后仍由后端决定是否实际调用 Provider。
4. 网页引用只通过净化 `href` 安全打开，恶意 scheme/凭据 URL 被拒绝。
5. 敏感 Dataset 和内部文档内容不会被前端发送到 Web。
6. Web 失败不破坏已有本地回答状态。
7. 两个设置默认均为关闭，按用户/标签页刷新恢复，身份变化时清除；主开关关闭或无 capability 时请求始终显式发送两个 `false`。
8. Unknown Web event 的原始 payload 不进入 Timeline、console、Query Cache 或持久化存储。

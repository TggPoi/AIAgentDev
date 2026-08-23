# 联网搜索 Feature

## 1. 目标与边界

允许具备 Web Search Tool 权限的用户在对话前决定是否允许联网，并在统一事件时间线和来源区查看结果。无独立 Web 页面或问答接口，只使用 `POST /rag/chat/stream/events`。

## 2. 能力与运行时条件

`GET /auth/capabilities` 的 `can_use_web_search` 决定是否显示控制；该值只代表权限存在，不保证外部 Provider 当前可用。后端运行时开关、Router、来源策略和 Tool permission 仍会在请求中裁决。

- 无能力：隐藏开关，并提交 `allow_direct_web=false`、`allow_web_fallback=false`。
- 有能力且关闭：两个字段均为 false。
- 有能力且开启：允许直接公开 Web 查询；fallback 是否同时开启在 UI 中明确说明或独立控制，不把两个语义混为一个隐式默认。

`allow_direct_web` 表示用户明确公开 Web 查询；`allow_web_fallback` 表示复杂研究在本地证据不足时允许外部补充。开启不代表一定调用。

## 3. 事件与来源

Web 工具进度使用 RagAgent 的任务/工具事件显示，未知新增事件按聊天时间线兼容规则保留。最终网页引用是 `RagSource`：`source_type=web`、标题、`href`、`content_preview` 和其他安全摘要。

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

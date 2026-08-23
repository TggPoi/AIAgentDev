# 联网搜索 Feature

## 1. 目标

允许拥有 Web Search Tool 权限的用户在对话前决定是否允许联网，并在统一事件时间线中查看搜索过程和网页来源。

## 2. interface 边界

联网搜索不创建独立页面或问答接口，只通过：

```text
POST /rag/chat/stream/events
```

执行。

## 3. 页面交互

- `can_use_web_search=false`：不显示联网开关，请求固定关闭 Web。
- `can_use_web_search=true`：显示开关，由用户明确选择。
- 关闭时提交：

```json
{
  "allow_direct_web": false,
  "allow_web_fallback": false
}
```

- 开启时允许直接公开 Web 查询和知识不足后的 Web fallback；最终是否调用仍由后端 Router、来源策略和 Tool permission 决定。

## 4. 来源展示

网页来源至少包含：

```text
title
href
domain
content_preview
```

- `href` 必须是后端返回的显式可信字段，前端不从任意 metadata 猜测。
- 外链使用新标签页和 `noopener noreferrer`。
- 页面区分知识文档来源和网页来源。

## 5. 安全与隐私

- 开启 Web 前提示：公开问题可能发送到外部搜索服务。
- 后端负责阻止敏感 Dataset 内容、内部文档正文或权限字段被发送到 Web。
- 前端不能通过显示开关绕过 Tool permission。

## 6. 验收标准

1. 无权限用户不能看到或伪造启用 Web。
2. 关闭 Web 时直接查询和 fallback 都不会调用外部搜索。
3. 开启 Web 后仍由后端决定是否需要调用。
4. 网页引用展示标题、域名并可安全打开。
5. Web Tool 失败显示结构化事件，不破坏已有本地 RAG 回答状态。

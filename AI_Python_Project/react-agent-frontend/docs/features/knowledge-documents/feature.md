# 知识文档 Feature

## 1. 目标与访问规则

让用户浏览当前权限范围内的 GitLab 正式文档、阅读只读提取内容、从 Agent 来源跳转原文并下载固定 revision 的源文件。

用户可读取公共文档、自己所属部门的全部文档，以及其他部门主管或管理员明确授予的单篇文档。列表、详情、预览、下载和 RAG 检索共享后端 ACL；前端不计算或扩展范围。

## 2. 后端契约

| 接口 | 说明 |
| --- | --- |
| `GET /knowledge/documents` | 支持 `query`、`department_code`、`document_type`、`cursor`、`limit` |
| `GET /knowledge/documents/{doc_id}` | 元数据详情 |
| `GET /knowledge/documents/{doc_id}/content` | 有界文本预览 |
| `GET /knowledge/documents/{doc_id}/download` | 认证下载原文件 |

列表项字段包括 `doc_id`、`title`、`file_name`、`repository_path`、`department_code`、`document_type`、`source_revision`、`updated_at`、`access_source`。详情另含 `source_id`、`source_project_path`、`visibility`。

`document_type` 是 `markdown|text|pdf|powerpoint|spreadsheet|word`。内容响应提供 `render_mode` (`markdown|plain_text|extracted_text`)、`content`、`truncated`、`warnings` 和实际 `source_revision`。

## 3. 页面实现

文档列表使用 URL 保存关键词、部门和类型筛选，按不透明 cursor 追加。卡片展示标题、部门、格式、更新时间和 `access_source`，但不把授权来源当作前端 ACL。

详情页先读元数据，再并行或按需读取内容。Markdown 经过净化渲染且禁用原始 HTML；纯文本保留换行；提取文本明确提示不保留 PDF/Office 原排版。`truncated` 或 warnings 显示非阻断提示。

## 4. 下载与缓存

下载必须通过共享 HTTP client 携带 Bearer 获取 Blob，从响应头解析经过后端处理的文件名，创建 object URL 触发保存并立即 revoke。不得直接导航受保护 URL，也不得让浏览器接触 GitLab Token 或私有 GitLab 地址。

详情和内容 Query Key 同时包含 `doc_id`；响应 revision 改变时清除旧内容缓存。Grant 创建或撤销后失效文档列表；已打开的跨部门文档在下一次请求收到隐藏式 `404` 时回到列表。

## 5. 安全与失败处理

- `404` 统一表示“文档不可用”，不区分不存在与无权读取。
- 不根据 repository path 拼 GitLab URL，不从来源 metadata 猜下载地址。
- `access_source` 只作说明，所有请求仍由服务端实时授权。
- 下载失败不保留部分 Blob，不在日志中记录正文。
- 从聊天来源进入时只接受稳定 `doc_id`。

## 6. 验收测试

1. 同部门用户可列出、预览并下载该部门文档。
2. 未授权用户无法枚举其他部门文档。
3. 单篇 grant 只开放目标文档，不扩大到整个外部门。
4. grant 撤销后列表、详情、内容、下载和 RAG 同时失效。
5. Markdown、纯文本和提取文本按 render mode 安全显示。
6. 下载内容与详情/预览的 `source_revision` 一致。

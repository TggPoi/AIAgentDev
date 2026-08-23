# 知识文档 Feature

## 1. 目标

让用户浏览当前权限范围内的 GitLab 正式发布文档、阅读只读预览、从 Agent 引用跳转原文并下载固定 revision 的源文件。

## 2. 数据来源

- 文档目录、`doc_id`、路径、revision、类型和源 ACL 来自 GitLab 文档事实表。
- 原始文件由后端 GitLab adapter 使用服务器端 Token 读取。
- 前端不访问 GitLab 私有地址，不保存或接收 GitLab Token。

## 3. 访问规则

用户可读范围是：

```text
公共文档
OR 自己所属部门的全部文档
OR 其他部门主管/管理员明确授予的单篇文档
```

列表、详情、预览、下载和 RAG 检索必须得到一致结果。

## 4. 页面

### 4.1 文档列表

- 分页或 cursor 加载。
- 按标题/路径关键词、部门和类型过滤。
- 展示标题、路径、部门、类型、更新时间和授权来源。

### 4.2 文档详情

- 展示元数据和只读正文。
- Markdown/TXT 原样文本渲染；不启用原始 HTML。
- PDF、DOCX、PPTX、XLSX 首期使用后端抽取文本预览，明确标注“预览可能不保留原排版”。
- 提供源文件下载。

## 5. 前端 interface

```text
listDocuments(filters, cursor) -> Page<DocumentSummary>
getDocument(docId) -> DocumentDetail
getDocumentContent(docId) -> DocumentPreview
downloadDocument(docId) -> BlobDownload
```

## 6. 一致性与缓存

- 文档响应包含 `source_revision`；预览和下载都读取该固定 revision。
- revision 改变时，旧预览缓存必须失效。
- 404 表示不存在或不对当前用户公开；是否使用 403 由后端统一安全策略决定。
- 下载文件名只能来自经过后端净化的仓库 basename。

## 7. 验收标准

1. 同部门用户能看到该部门全部文档。
2. 未授权用户看不到其他部门文档。
3. 获得单篇跨部门 grant 后，列表、详情、下载和 RAG 都能访问该文档，但不能访问同部门其他文档。
4. grant 撤销后上述四条链路同时失效。
5. Agent 文档引用能通过 `doc_id` 打开正确详情。
6. 下载内容与显示 revision 一致。

# Ingestion 模块

该模块负责把本地语料、异步 Office Import、GitLab 发布和 Agent Markdown 产生的文档转换为统一的 RAG Store 记录。

当前支持：

- Markdown / Text；
- PPTX / XLSX；
- DOCX / PDF；
- PPTX、DOCX、PDF 中的 raster 图片经 Qwen Vision 转换为结构化文字；
- Markdown parent-child、ACL、Embedding、ES/Milvus 双写；
- PostgreSQL advisory lock 串行化所有 Store mutation；
- local corpus scoped rebuild、manifest、journal 和 crash recovery。

## 处理主线

```text
原始文件
→ validate_knowledge_document_package()
→ 格式专用 Loader（只解析，不调用模型）
→ DocumentVisionService（图片预算、缓存、并发、租约 hook）
→ 格式专用 Builder
→ ProcessedKnowledgeDocument(parents, chunks, warnings)
→ Embedding
→ StoreMutationLock
→ ES / Milvus mutation 与收敛校验
```

RAG 回答模型仍然只接收文本 `RagContext`。原图、Base64 和 `normalized_bytes` 不进入 ES、Milvus、TaskPlan、SSE、报告或业务日志。Vision SDK tracing 被禁用，防止多模态消息进入 LangSmith。

## 格式边界

### Markdown / Text

Markdown 继续使用 `MarkdownHierarchyBuilder`：parent 和 child 都写 ES，只有 child 写 Milvus。Text 使用既有字符/token 分块。

### PPTX

提取 slide 文本、表格、备注和可安全解码的 raster picture。单个 Shape 失败只产生 warning；EMF/WMF/SVG 等不安全格式不会阻断普通文本导入。

### DOCX

支持正文 paragraph、list、table、table cell 和 inline image。图片 occurrence 保留 block 位置，同内容可复用 Vision 结果。header/footer、textbox、footnote/endnote、批注和绘图画布属于首版 unsupported scope。

Word 先构造 block，再按完整 block 装箱；只有单个 block 超限时才在块内拆分。图片说明始终与所属 block 一起进入 Chunk。

### PDF

原生文字页使用 pypdf 文本并只分析该页内容流实际绘制的 embedded image。无可见文字的扫描候选页使用 PDFium 整页渲染，不再重复分析 embedded image。

PDFium 的创建、取页、render、PIL 转换和 close 全部受 module-level mutex 保护。`pypdfium2` 分发包含 PDFium 二进制，发布制品时需要履行其许可证告知义务，本项目不宣称零许可证风险。

### XLSX

保持现有 Profile 语义。local corpus 优先读取 `<filename>.xlsx.profile.json`；缺少 sidecar 时 CLI 必须显式传 `--excel-default-mode section`。

## Vision 安全与资源预算

`VISION_ENABLED=false` 是默认值。开启时使用 `QwenVisionClient`，SDK retry 为 0，技术重试和 structured-output transport fallback 统一由 `invoke_structured_model()` 控制。

主要预算：

- 单图字节和像素上限；
- 每文档唯一图片内容数上限；
- 每文档标准化图片总字节上限；
- 扫描页数量上限；
- Provider 并发、timeout 和总调用次数上限。

同一图片多次出现时保留所有 occurrence，但按内容 SHA 去重 Provider 调用。共享磁盘 cache 默认关闭；开启后只保存结构化识别结果，不保存原图、路径、ACL 或用户信息。缓存文件以 PID/UUID 临时名完整写入并 `fsync + os.replace`，只保证跨进程原子读取，不宣称跨 Worker single-flight。

## 所有权与写入互斥

local corpus 记录包含：

```text
ownership_type=local_corpus
local_corpus_id=local-knowledge-base
source_id=local:local-knowledge-base
source_revision=<源文件 SHA256>
valid_from_version=0
valid_to_version=0
```

GitLab、Office Import 和 Agent Markdown 不得绕过 `StoreMutationLock`。等待锁期间丢失租约的 Worker 必须在 mutation 前再次校验 ownership；Vision 每次真实 Provider 请求前也会执行格式无关的 `before_external_call` hook。

## Local corpus scoped rebuild

`scripts/rebuild_local_knowledge_corpus.py` 先完成全部 parsing、Vision 和 Embedding，再允许 mutation。dry-run 会写入忽略 Git 的敏感 prebuild bundle 和审查报告；正式提交必须接受准确的 report SHA。

```powershell
$env:PYTHONPATH="src"

.\.venv\Scripts\python.exe -B scripts\rebuild_local_knowledge_corpus.py `
  --source-dir docs\knowledge-base-acl-test `
  --dry-run `
  --excel-default-mode section `
  --vision-enabled

.\.venv\Scripts\python.exe -B scripts\rebuild_local_knowledge_corpus.py `
  --source-dir docs\knowledge-base-acl-test `
  --commit `
  --accept-report-sha256 <dry-run 输出的 SHA256> `
  --local-corpus-id local-knowledge-base `
  --vision-enabled
```

提交只变更 `source_id=local:local-knowledge-base` 的记录。journal 状态为：

```text
prepared → mutating → stores_verified → manifest_published → committed
```

发生失败时，recovery bundle 用于恢复旧 local records/vectors 和旧 manifest；其他 ownership 不进入 snapshot 或删除集合。

## 关键代码

- `processing/structured_document_processor.py`：统一编排、格式专用 Builder；
- `processing/document_vision.py`：Vision 预算、缓存、并发和 occurrence 映射；
- `processing/word_processing.py` / `pdf_processing.py`：DOCX/PDF Loader；
- `validation/document_validation.py`：统一格式校验 dispatcher；
- `stores/store_mutation_lock.py`：PostgreSQL advisory lock；
- `stores/scoped_corpus_writer.py`：local corpus 提交、manifest、journal 和恢复；
- `worker.py`：Office Import lease-aware 处理；
- `integrations/gitlab/sync_service.py`：GitLab full/incremental/bootstrap。

## 回归入口

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -B scripts\tests\ingestion\test_document_vision_processing.py
.\.venv\Scripts\python.exe -B scripts\tests\ingestion\test_local_corpus_and_store_lock.py
.\.venv\Scripts\python.exe -B scripts\tests\ingestion\test_office_ingestion.py
.\.venv\Scripts\python.exe -B scripts\tests\integrations\test_gitlab_enterprise_sync.py
```

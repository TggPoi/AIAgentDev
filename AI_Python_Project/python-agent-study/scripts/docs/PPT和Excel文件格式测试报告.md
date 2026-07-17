# PPT、Excel、Markdown 文件格式真实验收报告

## 1. 验收信息

- 验收日期：2026-07-15
- 运行编号：`20260715-230846`
- 原始文件备份：`runtime/office-acceptance/20260715-230846/originals`
- 验收原则：真实 PostgreSQL、Elasticsearch、Milvus、Worker 和外部模型链路；未执行项不标记为通过。
- 文件处置：验收完成后保留修改版本，原始版本由上述目录供人工对比。

## 2. 原始文件与基线 SHA-256

| 文件 | 部门 | 修改前 SHA-256 |
|---|---|---|
| `product_planning/UE5战斗系统设计方案_RAG测试用PPT.pptx` | `product_planning` | `67F56D30695F71D5DEB53EF39CA0246679047114BA7B3EC0FC44010FADB53FCB` |
| `development/游戏开发资产列表_RAG测试.xlsx` | `development` | `D377A34B6B31EC6CFD4271F90EBE79407D71275F756D448B83D35088FFF1D5FE` |
| `development/UE5战斗系统程序架构设计_RAG测试.md` | `development` | `2C466CED6C82DB1DBF229F0194C9735D9EB1B846B55BBD2C8674F5BF41202C72` |

备份后重新计算的三个 SHA-256 与原文件一致。

## 3. 只读基线检查

| 文件 | Loader / Builder 基线 | 结果 |
|---|---|---|
| PPTX | 11 页、`slide_id=256..266`、11 个 Chunk | 内容和备注可提取，无 extraction warning；源文件使用普通文本框而非标题占位符，metadata 标题退化为 `Slide n` |
| XLSX | 5 个可见 Sheet；整本 Section 模式 61 个 Chunk | 公式与缓存值双 Workbook 配对有效；固定字符切分会让部分 Chunk 从表格行中间开始 |
| XLSX `资产清单` | Record 模式、`资产ID` 为身份字段 | 45 条记录、45 个 Chunk，记录身份稳定 |
| Markdown | 84 个 Chunk | 标题路径和正文可解析；当前写入语义仍是文档级 replace |

### 3.1 验收前已复现的生产缺陷

1. `build_default_document_loader()` 同时返回 Office Loader，导致默认 Markdown ingestion 仍可能把 PPTX/XLSX 交给 `MarkdownChunkBuilder`。
2. PPTX 没有标题占位符时不推断页面标题，真实文件 11 页标题全部退化为 `Slide n`。
3. Excel Section 先渲染整张 Sheet 再按固定字符切分，可能切断一整行，破坏行坐标和人工可读性。

### 3.2 当时已知限制（已于 2026-07-16 修复）

初次验收时 Excel Profile 的 `mode` 只支持 Workbook 级别，混合工作簿不能在同一次导入中让
`资产清单` 使用 Record、其他 Sheet 使用 Section。该限制已通过 `mode=mixed + sheets[].mode`
解决，实现与补充验收证据见第 11 节。本节保留的是初次验收时的历史现状。

## 4. 最小修复与回归

已完成三个根因级最小修复：

| 缺陷 | 修复文件 | 修复方式 | 回归证据 |
|---|---|---|---|
| 默认 Markdown ingestion 接收 Office | `src/fast_app/ingestion/processing/document_loaders.py` | `build_default_document_loader()` 恢复为仅组合 `MarkdownDocumentLoader`、`TextDocumentLoader` | 新增 `test_default_loader_excludes_office()` |
| 无标题占位符时 PPT 标题退化 | `src/fast_app/ingestion/processing/document_loaders.py` | 按 `(top,left,shape_id)` 递归查找首个有效文本 Shape，并从正文提取中排除该 Shape | 真实生成无占位符 PPT，断言标题为 `Inferred title` 且正文不重复 |
| Excel Section 切断整行 | `src/fast_app/ingestion/processing/office_chunk_builders.py` | 表头加完整数据行贪心装箱；仅单行本身超限时调用行内 splitter | 构造两个无法同箱但可分别容纳的行，断言完整行文本各出现一次 |

回归命令：

```powershell
.\.venv\Scripts\python.exe scripts\test_office_ingestion.py
```

结果：通过，输出 `office ingestion checks passed`。该轮覆盖 Loader、专属 Builder、OOXML 拒绝、Middleware、API 合同、Worker heartbeat、幂等模拟和新增修复断言；真实数据库/存储开关将在服务启动后另行执行。

## 5. 服务环境

| 组件 | 实际状态 |
|---|---|
| PostgreSQL | `pgvector/pgvector:pg16`，容器 `pg_vector_db`，healthy |
| Alembic | current=`20260715_0008`，head=`20260715_0008` |
| Elasticsearch | 8.17.0，`docker-cluster`，IK analyzer 已安装，目标索引 `python_agent_demo_chunks` |
| Milvus | 2.6.13，容器 healthy，目标 Collection `python_agent_demo_chunks` 已存在 |
| FastAPI | `http://127.0.0.1:8000/health` 返回 `{"status":"ok"}` |
| OpenAPI | 已确认创建、更新、Excel Profile、任务查询和 `/rag/chat` 路由存在 |
| 模型配置 | Qwen `text-embedding-v4`，1024 维；DashScope reranker；Qwen LLM |

隔离资源真实回归命令：

```powershell
.\.venv\Scripts\python.exe scripts\test_office_ingestion.py --real-db --real-stores --real-worker
```

结果：通过。真实 PostgreSQL 并发领取/租约回收、真实 ES/Milvus 增量收敛、真实 Worker 创建和插页更新均通过；该脚本的 Worker 使用 3 维 Mock Embedding，只证明本地基础设施和增量协议，不替代后续真实 Qwen 验收。

### 5.1 外部模型安全阻塞记录

首次 PPT 创建任务 `import_17c3ed1417c24988a993183aa45b2368` 已真实执行到 `embedding` 阶段；Loader、Builder、ES/Milvus 现状读取和 diff 均成功。沙箱阻止连接外部 Qwen，任务按设计回到 `pending`。申请解除网络限制时，安全审查明确拒绝把工作区内私有 Office 正文发送给外部 Qwen，要求在告知数据外发风险后取得用户的再次明确授权。

用户随后再次明确授权把这三个测试文档的内容发送给上述外部模型服务。本轮恢复后始终设置
`LANGSMITH_TRACING=false`，并完成真实 Qwen Embedding、DashScope Reranker 和 Qwen LLM 验收；
结果见第 7～9 节。这里保留首次暂停记录，是为了说明为什么存在一组已清理的中间任务。

暂停前一致性处理：确认两个待创建 `doc_id` 在 ES/Milvus 中均为 0 Chunk；删除本轮两个未完成任务及 pending 注册记录、删除精确 staging 文件，并把 PPTX/XLSX 原文件恢复到知识库路径。恢复后 SHA-256 与本报告第 2 节完全一致，未留下半成品索引或缺失目标文件。

## 6. 基础导入与 Chunk 验收

### 6.1 PPTX

- create job：`import_87838bdf04054196a8d3ecdd5f96c4db`
- doc_id：`doc_81ba7c85ae484df0`
- 状态：`succeeded / completed`
- PostgreSQL 文档版本：1，SHA 与原始文件一致。
- Chunk：11；diff=`added 11, embedded 11`，其余为 0。
- 标题修复生效：第一页 metadata title 为 `UE5 引擎实现战斗系统的设计方案`，不再退化为 `Slide 1`。
- `slide_id=256`、`slide_number=1`、`section_path=["Slide 1: UE5 引擎实现战斗系统的设计方案"]` 正确。
- 11 页备注均进入正文；无 extraction warning。

### 6.2 XLSX Section

- create job：`import_6350e8172f814662bde7f087c0c61d33`
- doc_id：`doc_570ac386aa95cc44`
- 首次执行状态：按预期进入 `awaiting_configuration`。
- preview fingerprint：`dc3cc73785f6cac68451f14883ff31c0b2e5fdbae90c44e5fe6ba97ab6a8f35e`
- active Profile：`excel_profile_3a4853e2d116443a90ff87cbc79939a2`，version=1，mode=`section`。
- 确认后状态：`succeeded / completed`；文档版本 1，SHA 与原始文件一致。
- Chunk：33；diff=`added 33, embedded 33`，其余为 0。
- 修复前只读基线的固定字符 splitter 为 61 个 Chunk；完整行贪心装箱后为 33 个 Chunk。每个 Chunk 重复 Sheet/列头，数据行保持完整，边界更适合人工复查和坐标检索。
- 5 个 Sheet 均被索引；示例 Chunk 保留 `Sheet: 资产清单`、`Rows 1-100`、A-W 列和原始行号。
- 公式/缓存值双 Workbook 配对有效；Worker 读取时 openpyxl 仅报告“不支持的扩展若保存会被移除”的运行时 warning，本次 Loader 为只读，没有保存源文件，也没有任务 warning。

### 6.3 Markdown

- doc_id：`doc_24f9024466249c44`
- 仅选择目标文件，经 `MarkdownDocumentLoader + MarkdownChunkBuilder + replace_docs_rag_stores()` 写入。
- Chunk：84；ES/Milvus 各成功写入 84。
- 首 Chunk 为 YAML front matter，随后按 Markdown 标题形成稳定 `section_path`。
- Markdown 不写 Office PostgreSQL 注册表，符合当前职责边界。

### 6.4 基础双存储对账

| 文档 | ES | Milvus | ID 集合 | Office Hash | 向量维度 |
|---|---:|---:|---|---|---|
| PPTX | 11 | 11 | 完全一致 | content_hash/index_hash 完全一致 | 1024 |
| XLSX | 33 | 33 | 完全一致 | content_hash/index_hash 完全一致 | 1024 |
| Markdown | 84 | 84 | 完全一致 | 不适用（现有 Markdown metadata 无 Office Hash） | 1024 |

ACL 抽查：PPTX 为 `allowed_departments=[product_planning]`；XLSX、Markdown 为 `allowed_departments=[development]`。source_path、文件类型和文件名均与源文件一致。

## 7. 修改场景与增量对比

### 7.1 PPT 中间插页、修改原页

保留在工作区的修改：

- 原第 5 页正文 `0.15~0.25 秒` 改为 `0.18~0.28 秒 (PPT_INCREMENTAL_EDIT_20260715)`。
- 在原第 5 页后插入 `5A. 增量更新验证页`，正文标记 `PPT_INSERT_MARKER_20260715`，同时写入备注标记。
- 原 slide ID 为 `256..266`；修改后为 `256,257,258,259,260,267,261..266`。插页没有改变后续原页面的 slide ID。
- 修改后 SHA-256：`2BA3B1CF0F484F39DF8AB377844C691A0ED1186E0173068164DE144337E20229`。

更新任务：

- job：`import_d33f2117ca064c29a031b2d6586da6ba`
- 状态：`succeeded / completed`
- 文档版本：2
- Chunk：12
- diff：`added=1, changed=1, metadata_only=6, unchanged=4, embedded=2, removed=0`

向量基线逐 ID 比较：11 个旧 Chunk ID 全部存在；10 个旧向量指纹完全不变；只有原第 5 页
`chunk_4fa2c1cee4de0e73` 的向量改变；新增页只有新 Chunk
`chunk_633fcabfcec448b8`。这与“修改页重新 Embedding、后续 6 页仅页码 metadata-only、新页新增”完全一致。

### 7.2 Excel Section 中间插行、插列

通过 Excel COM 修改并保留：

- `资产清单` 第 25 行插入资产 `AST-ACCEPT-20260715`，负责人为 `验收负责人`，包含标记 `EXCEL_INSERT_MARKER_20260715`。
- 在原负责人附近插入 L 列 `审核人`，已有数据填入 `技术美术复核组`。
- 修改后工作表为 47 条非空行（含表头）、A-X 共 24 列。
- 修改后 SHA-256：`5EE52EECB7AA9D62CD4DF97C9EE064C0AB4758F15A52B1CB07842D7130C85295`。

真实更新首先发现一个生产缺陷：openpyxl 的 read-only Worksheet 在部分文件上会出现
`max_column=None`，导致 `source_columns` 不稳定。已在
`src/fast_app/ingestion/processing/document_loaders.py` 中对该情况调用
`calculate_dimension(force=True)`，新增回归后先按旧文件回滚索引，再重新提交修改文件。

最终更新任务：

- job：`import_282a7b3a3ea64196b83ca5ea6efc0a79`
- 状态：`succeeded / completed`
- 文档版本：4（包含缺陷现场、回滚和最终更新）
- Chunk：39
- diff：`added=6, changed=28, unchanged=5, embedded=34, removed=0`

5 个不依赖资产表结构的 Chunk 完全未写入。`资产汇总` 中有 2 个公式 Chunk 随插行/插列后引用范围变化，
因此合法地计入 changed；这说明“其他 Sheet 一律不变”不能应用于含跨 Sheet 公式依赖的工作簿。

### 7.3 Excel Record 独立验收

从原始备份生成仅含 `资产清单` 的临时工作簿，以 `资产ID` 为 `row_identity`，配置 23 个语义字段：

- 首次导入 45 条记录、45 个 Chunk。
- 更新时插入 `AST-RECORD-20260715`、移动列、只修改 AST-0002 的优先级，并加入一个有值未知列。
- 未知列使任务按预期进入 `awaiting_configuration`，未被静默忽略。
- 确认新增字段的 draft Profile 后成功，得到 46 条记录。
- diff：`added=1, changed=1, metadata_only=44, embedded=2`。
- 45 个共同记录的 Chunk ID 全部稳定；44 个未改记录 content_hash 和向量不变；只有 AST-0002 重新 Embedding；新增资产只有 1 个新 Chunk。

验收后已删除临时文件、2 个任务、4 个 Profile 和文档注册；最终 PostgreSQL、ES、Milvus 中该临时
doc_id `doc_af9c6ac059776121` 均为 0。

### 7.4 Markdown 新增章节

- 末尾新增 `## 32. 增量更新测试` 和标记 `MARKDOWN_INCREMENTAL_MARKER_20260715`。
- 修改后 SHA-256：`B0B51CFADC0C92AACD8186AD334EB40A92DE2D4736BCFDB75AD472F680A872F6`。
- 更新后 85 个 Chunk；新 Chunk 为 `chunk_a17565f13e822fca`，section_path 为
  `["32. 增量更新测试"]`。
- 真实文件暴露了 Markdown 标题栈把同级 `##` 错误嵌套的问题；已改为保存真实 heading level 并新增回归。
- Markdown 仍执行文档级 replace，本次 85 个 Chunk 全部重新 Embedding；它不具备 Office 的增量 Hash 写入。

### 7.5 真实链路额外修复

`/rag/chat` 首次验收发现 Router 不是检索失败，而是 Qwen 结构化输出集成失败：

1. Qwen3.6 Flash 默认 thinking 与 required function calling 冲突，DashScope 返回 400。现仅对 Qwen Router 注入
   `extra_body={"enable_thinking": false}`。
2. Qwen 会为非澄清意图输出 `clarification_question: ""`。现将空白可选字段规范化为 `None`，仍拒绝非空越界字段。

修复后真实 Router 20 个用例准确率由 70% 最终提升为 100%，没有新增普通问答关键词旁路。

## 8. PostgreSQL / ES / Milvus 对账

### 8.1 PostgreSQL 最终状态

| 文档 | 版本 | 状态 | 当前 SHA / Profile |
|---|---:|---|---|
| PPTX `doc_81ba7c85ae484df0` | 2 | active | SHA=`2ba3...0229`，无 Excel Profile |
| XLSX `doc_570ac386aa95cc44` | 4 | active | SHA=`5ee5...5295`，active Profile=`excel_profile_3a4853e2d116443a90ff87cbc79939a2` |
| Markdown | 不注册 | 不适用 | 继续遵循 Markdown ingestion 的现有职责边界 |

最终 active import job 数为 0。PPT、Excel 创建与最终更新任务均为 `succeeded / completed`；任务中的
chunk_count、diff_counts 与第 7 节实测一致。Excel active Profile 为 version 1、mode=`section`。

### 8.2 双存储最终状态

| 文档 | ES | Milvus | ID 集合 | content/index Hash | 向量维度 |
|---|---:|---:|---|---|---|
| PPTX | 12 | 12 | 完全一致 | 完全一致 | 1024 |
| XLSX | 39 | 39 | 完全一致 | 完全一致 | 1024 |
| Markdown | 85 | 85 | 完全一致 | 不适用 | 1024 |

三个最终唯一标记在各自 doc_id 下均命中 1 个 ES Chunk。临时 Record 文档 ES=0、Milvus=0、PostgreSQL
注册不存在；没有旧版本额外主键。ACL 和 source_path 仍与部门和源文件一致。

## 9. 真实检索结果

验收时 `LANGSMITH_TRACING=false`，使用真实 Qwen Embedding、DashScope Reranker 和 Qwen LLM，所有
`/rag/chat` 请求均使用精确 `source_path` filter。

### 9.1 直接 Keyword / Vector

| 问题 | Keyword 证据 | Vector 证据 | 判断 |
|---|---|---|---|
| 输入缓存窗口建议是多少秒？ | top1=`chunk_633fcabfcec448b8`，score=14.458105 | top1 同 Chunk，score=0.495927 | 命中新插 Slide；原修改页也在前列 |
| AST-0002 负责人和优先级 | top1=`chunk_1ee1723550f400fe`，score=13.822773 | top1 同 Chunk，score=0.655484 | 命中 `资产清单` |
| 新增 Excel 标记 | 资产表 Chunk 在 keyword top2、vector top2 | 两路均可召回 | top1 被同文档的“增量”说明文本竞争，rerank 后主记录为 top1 |
| 为什么不在 Anim Notify 决定最终伤害？ | 正确 9.3 Chunk 为 top2，score=21.060425 | 正确 9.3 Chunk 为 top1，score=0.82257 | 命中职责与风险章节 |

### 9.2 `/rag/chat` Hybrid

| 问题 | request_id | 实际答案 | 首要来源 |
|---|---|---|---|
| 输入缓存窗口建议是多少秒？ | `ada4b5d2909a4b41ab9107f7a84d1b95` | 动态窗口 `0.18~0.28 秒`；同时区分备注中仍保留的 `0.15~0.25 秒` | Slide 5 `chunk_4fa2...`，新 Slide 6 `chunk_633f...` |
| AST-0002 负责人和优先级 | `830be4ad3e3c401aaaf299284d490b37` | `赵凯 / P1` | `资产清单`、Rows 1-100，`chunk_1ee172...` |
| AST-ACCEPT-20260715 负责人 | `bf40b1eda2af46b98b5569bdf80e9e04` | `验收负责人` | `资产清单`、Rows 1-100，`chunk_21943...` |
| 为什么不在 Anim Notify 决定最终伤害？ | `e44c2d1622a6438dbde19df861325503` | 正确说明服务端权威、动画职责和网络/测试风险 | 9.3、29.2 和新增 32 章节 |

答案内容、Chunk ID、部门 ACL、PPT Slide、Excel Sheet/区域和 Markdown section_path 均正确。需要如实说明：
Section 模式来源 metadata 返回的是区域 `Rows 1-100`，列坐标保存在 Chunk 表头 A-X 和行内容中，不能像
Record 模式那样把单条命中的精确行号/字段坐标作为独立 source metadata 返回。

真实 Router 最终回归命令：

```powershell
$env:LANGSMITH_TRACING='false'
.\.venv\Scripts\python.exe scripts\phase_15\test_agent_task_router_real_llm.py
```

结果：20/20，通过。

## 10. 初次验收结论

初次验收结论：**部分通过**。

通过项：

- 三种文件的 Loader、Chunk 边界、真实 Embedding 和双存储写入正确。
- PPT 插页/改页实现稳定 ID、metadata-only 向量复用和最小 Embedding。
- Excel Section 插行/插列后仅重建受结构或公式依赖影响的 Chunk；Record 模式的行列移动、未知列确认和单记录增量符合预期。
- PostgreSQL 文档版本、任务、Profile 与最终文件 SHA 一致；ES/Milvus 完全收敛。
- 四个真实 hybrid 问题均返回正确答案和正确文档来源；Router 真实 20 用例通过。
- Office、Markdown、Router 单元回归、真实 DB/Store/Worker 回归、OpenAPI、迁移头、`py_compile` 和
  `git diff --check` 均通过。

初次验收时不能标记为完全通过的剩余限制：

1. Excel Profile 当时仍是 Workbook 级 mode，不支持同一工作簿内 Record/Section 混合模式；该项已在第 11 节完成修复。
2. Excel Section 的 source metadata 只精确到 Sheet/区域；第 11 节已将需要业务记录精确定位的 `资产清单`
   切换为 Record，其他 Section Sheet 则返回实际行范围和列集合。
3. Markdown 仍是文档级 replace，不具备 Office 的 content_hash/index_hash 增量更新。
4. 真实 `/rag/chat` 单次耗时有明显波动；本轮最慢批次约 247 秒完成 4 个顺序请求，正确性通过，但上线前仍应单独做延迟与超时基线。

修改后的三个测试文件按约定保留；原始文件和修改前 SHA 可从第 1、2 节所列备份目录人工复查。

## 11. Sheet 级 Mixed Record/Section 补充验收（2026-07-16）

### 11.1 实现范围

- Excel Profile 新增 `mode=mixed`，每个 Sheet 通过 `sheets[].mode=record|section` 选择分块模式。
- 旧 `mode=record|section` Profile 仍允许 Sheet 省略 mode 并继承 Workbook mode；历史
  `mode=section, sheets=[]` 仍走整本 Section 逻辑。
- Excel 更新端点新增 multipart 字段 `reconfigure_excel_profile`。设为 `true` 时不复用 active
  Profile，Worker 重新生成预览并进入 `awaiting_configuration`；非 Excel 请求返回 422。
- `ExcelChunkBuilder` 按 Sheet 分派到现有 Record/Section 逻辑，没有新增 Builder、数据库表或
  RAG source 类型。
- Section Chunk 现返回该 Chunk 实际包含的 `row_start/row_end`，以及物理列集合
  `source_columns`；这些坐标参与 `index_hash`。

### 11.2 自动回归

执行命令：

```powershell
.\.venv\Scripts\python.exe scripts\test_office_ingestion.py --real-db --real-stores --real-worker
```

结果：通过，输出 `office ingestion checks passed`。新增断言覆盖：

- mixed Profile 成功，缺少 Sheet mode、重复 `sheet_key`、无效 Record 主键和非 Excel 重配置均被拒绝。
- 同一 Workbook 同时生成 Record 和 Section Chunk。
- AST-0002 前插行、负责人附近移动列后，Chunk ID 和 `content_hash` 不变，
  `row_number/field_coordinates/index_hash` 变化，diff 为 metadata-only 且不重新 Embedding。
- 修改 AST-0002 单元格后只改变该 Record Chunk 的 `content_hash`。
- Section metadata 使用 Chunk 实际行范围和完整物理列集合；超长单行拆分保留同一真实行号。
- 真实 PostgreSQL 并发领取/租约回收、真实 ES/Milvus 增量收敛和真实 Worker 回归均通过。

### 11.3 真实工作簿的本地隔离存储验收

对当前 `游戏开发资产列表_RAG测试.xlsx`原文件构造下列 mixed Profile：

| Sheet | mode | 结果 |
|---|---|---|
| `资产清单` | Record | 46 个 Record Chunk |
| `分类说明` | Section | 1 个 Chunk，Rows 1-9，A-D |
| `许可证与供应商` | Section | 1 个 Chunk，Rows 1-8，A-F |
| `资产汇总` | Section | 1 个 Chunk，Rows 1-13，A-H |
| `RAG测试说明` | Section | 1 个 Chunk，Rows 1-12，A-C |

本次使用真实 Elasticsearch/Milvus 的临时隔离索引/集合和 3 维本地 Mock Embedding，不写入正式文档集合。
结果为总计 50 个 Chunk，ES=50、Milvus=50，ID 集合完全一致，`verify_chunk_convergence()` 通过。
隔离资源在验收后已删除。

AST-0002 实际 metadata：

```json
{
  "excel_mode": "record",
  "row_identity": "AST-0002",
  "row_number": 3,
  "field_coordinates": {
    "owner": "K3",
    "priority": "N3"
  }
}
```

这证明之前的“只能返回 `Sheet=资产清单, Rows 1-100`”缺口在 Builder、metadata 和双存储层已修复。

### 11.4 真实更新任务与安全恢复

通过更新端点以相同 SHA 和 `reconfigure_excel_profile=true` 创建真实任务
`import_8dc3640273d942f1a20ec6168396edfc`。Worker 正确进入 `awaiting_configuration`，预览指纹为
`7eb8e6ab688c8aaecb28bf6c0030fa31822965b6c680c824aaa06a2393353a50`，并成功保存 version 2、
mode=`mixed` 的 draft Profile `excel_profile_ccca4a4a9f654818bdbc4cfdb537964a`。

继续执行真实 Qwen Embedding 时，当前运行环境的安全策略拒绝了将工作区文档内容发送到外部模型服务。
本轮没有绕过该限制，因此没有执行新 mixed Profile 在正式 1024 维集合中的 Embedding、激活与
`/rag/chat` 精确坐标终验收。

为避免留下半完成状态，已删除上述任务、draft Profile 和 staging 文件。清理后实测：

- 文档 `doc_570ac386aa95cc44` 仍为 version 4，SHA 为 `5ee52e...5295`。
- active Profile 仍为旧 Section Profile `excel_profile_3a4853e2d116443a90ff87cbc79939a2`。
- 活动导入任务数为 0；上述任务和 draft Profile 均已不存在。
- 正式 Excel doc_id 在 ES/Milvus 中仍为 39/39，ID 集合一致。

### 11.5 补充验收结论

结论：**功能实现与本地真实存储验收通过；外部模型的正式 mixed 激活与 `/rag/chat` 验收未执行。**

因此，原报告中“Workbook 不支持混合模式”和“资产清单无法返回精确行列 metadata”两个代码缺口已修复。
但按“未执行项不写通过”的原则，整份报告仍不将外部 Qwen 终到终 mixed 链路标记为通过。

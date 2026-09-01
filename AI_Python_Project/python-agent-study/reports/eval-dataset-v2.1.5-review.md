# RAG Eval 评测集 V2.1.5 Candidate 人工审核材料

## 1. 审核对象

- 数据集：`src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.5.json`
- 构建脚本：`.tmp/build_eval_dataset_v2_1_5.py`
- 离线契约测试：`scripts/tests/evaluation/test_eval_dataset_v2_1_5.py`
- `dataset_version`：`2.1.5`
- `lifecycle`：`candidate`
- Case：16 条（Reader 13 条，Operator 3 条）
- `knowledge_version`：0
- `source_revision`：`sha256:720ba93c1fa2f14d4da554921d0cd14a3e1d130c699fd2d641449f05600e0167`
- `content_sha256`：`5cbb639e5a032c2a6bb29fd2be53a371a50e78cc096e6dcb332ea34709d53124`
- 标注状态：全部 `pending_review`

V2.1.5 从不可变 V2.1.4 派生，没有原地修改 V2.1.4。除下面列出的 4 条
Case 外，其余 12 条 Case 的问题、qrels、关键事实和检索参数均保持不变。

## 2. 本轮修复原则

本轮明确区分两个集合：

1. `relevant_logical_chunk_ids`：能够直接帮助回答问题的语义相关 Chunk 全集，
   用于 Recall、Precision、HitRate 和 MRR。
2. `authoritative_logical_chunk_ids`：必须被命中的主证据子集，用于权威来源门禁。

相关 Chunk 可以提供补充、续页或重复图文证据，但不应因此全部成为“必须命中”的
权威来源。否则正确答案已经具备时，仅因没有同时召回重复证据，整次运行仍会被标为
`partial`。

## 3. 修正 Case

### 3.1 `reader_longdocs_toon_production_multi_source`

问题保持不变：

> 两份 UE5.8.1 长手册都说明官方 Toon 不能自动完成 Anime Character Pipeline。
> 它已经提供哪些基础能力，项目仍需自行补齐哪些角色渲染模块？

V2.1.5 相关 qrels：

| 文档 | 逻辑 Chunk | 作用 |
|---|---|---|
| DOCX | `chunk_f6b5cbc02b515961` | 官方 Toon 主正文：本地光、Sky Light、Lumen GI、BSDF/Profile/Ramp/Hatching/各向异性高光 |
| DOCX | `chunk_6f31fe460a4ff15b` | 官方底座无法自动解决 Face、头发、Outline、后处理 |
| PDF | `chunk_519c11634c2ef350` | 官方能力与仍需项目补齐模块的主说明 |
| PDF | `chunk_835a2d68531e3688` | Toon Profile、Diffuse/Specular 分段曲线续页 |
| PDF | `chunk_6fb6c9494ea6327d` | 官方入口不等于完整 Anime Character Pipeline |

权威来源：

- `chunk_f6b5cbc02b515961`
- `chunk_519c11634c2ef350`

这两个主证据分别来自 DOCX 和 PDF，可保证多来源 Case 至少命中两份长文档。

V2.1.4 的 `chunk_e6d54817043b7a3e` 被移出 qrels。它是全书背景总结，虽然提到
Face SDF、Outline 和官方 Toon，但没有直接回答“官方已有能力/仍缺模块”的完整边界。

### 3.2 `reader_pdf_mover_migration`

相关 qrels：

- `chunk_00499a8f184e0ffd`：8.1 Mover 主说明。
- `chunk_50f5a64967ad9d11`：8.1 对比表续页。
- `chunk_f67c617af929dfce`：旧技术迁移矩阵，明确 CMC 成熟、Mover Experimental、正式项目继续使用 CMC。
- `chunk_0c20779a4e397e0d`：10.1 对“CMC 已过时”的纠正。

权威来源：

- `chunk_00499a8f184e0ffd`
- `chunk_0c20779a4e397e0d`

迁移矩阵被补入语义相关全集，避免它被检索到时错误降低 Precision；但问题明确要求
8.1 和 10.1，因此权威门禁仍只要求两个点名章节的主证据。

### 3.3 `reader_pdf_nne_training_runtime`

5 个语义相关 qrels 保持不变：

- `chunk_fa9d79af16538c98`
- `chunk_dfec29f8331e1bd6`
- `chunk_c80e0436eac5de05`
- `chunk_1aacfb4570bf0fbe`
- `chunk_d8f7f46961b5a99e`

权威来源收敛为：

- `chunk_fa9d79af16538c98`：Learning Agents 的状态和用途。
- `chunk_dfec29f8331e1bd6`：训练、ONNX、NNE Model Data 主流程。
- `chunk_c80e0436eac5de05`：NNE Runtime 主说明。

`chunk_1aac...` 和 `chunk_d8f...` 仍是语义相关证据，但包含续页/重复图像信息，
不再要求二者必须与三个主证据同时进入 Top-5。

### 3.4 `reader_public_acl_underfilled`

问题仍然要求按章节概述限定 public 文档全文，因此 16 个子块继续全部作为语义
相关 qrels；`top_k=20`、`candidate_k=20` 和精确 `source_path` 不变。

权威来源改为与问题明确要求的章节一一对应的 12 个 Chunk：

- 项目目标：`chunk_5b810cc8195b5051`
- 测试目录：`chunk_1d4b9388b6b6a450`
- 权限模型：`chunk_9db8266b4400b809`
- 三部门预期行为：`chunk_ab6631bbb6b4315e`、`chunk_30679008b2e6d98b`、`chunk_f6a70fdc86583e29`
- 推荐问题与关键词：`chunk_34746fe25e2b2d22`、`chunk_308b696cf3ecd8cd`
- 验收标准：`chunk_0d557c0bdaaed986`
- 三类错误：`chunk_9306991da46132c3`、`chunk_aa8db320ce8941f2`、`chunk_f9fff42f4d54189d`

以下 4 个 Chunk 仍然与全文概述相关，但属于介绍、背景、概念区分或总结，不作为
必须命中的权威来源：

- `chunk_a96818cd638bdf5e`
- `chunk_0d712ae8b17bbe30`
- `chunk_46184d5a7c6d3eb2`
- `chunk_013212d0fb835c38`

同时新增关键事实 `test_directory_mapping`，因为问题明确询问测试目录，而 V2.1.4
的答案完整性事实中遗漏了这一项。

## 4. 不变边界

- 其余 12 条 Case 的业务语义没有变化。
- Reader/Operator 身份没有变化。
- ACL negative 和 no-result Case 没有变化。
- 父块 Case 仍按逻辑父块计分。
- 16 条 Case 的场景矩阵和 9 份文档覆盖没有变化。
- 所有 answerable Case 的相关身份数量都不超过 `top_k`。
- 没有修改 ES、Milvus、PostgreSQL、知识文档或 Eval 生产代码。
- 没有运行 RAG、Embedding、Reranker 或 DeepEval。

## 5. 数据库核对边界

2026-08-29 在 Docker 环境恢复后，已经针对最终 V2.1.5 和固定
`content_sha256` 完成只读整体验证：

- 47 个语义相关子块与 1 个禁止子块组成 48 个待核对子块。
- Elasticsearch 命中 49 条：48 个子块和 1 个父块，缺失 0、重复 0。
- Milvus 命中 48 条子块，缺失 0、重复 0；父块没有错误写入 Milvus。
- 数据集标注与 Elasticsearch 的 `doc_id`、`source_path`、`source_revision`
  差异为 0。
- Elasticsearch 与 Milvus 的正文、标题、文档身份、来源路径、来源修订、
  父子关系、Chunk 序号、版本区间和 ACL 差异为 0。
- 48 个子块类型均合法，父块类型为 `markdown_parent`，失效记录为 0。

本次只做精确身份和内容一致性查询，没有调用 Embedding、Reranker、LLM 或
DeepEval，也没有运行真实 RAG 评测。

## 6. 发布边界

2026-08-29 只读查询确认 `knowledge_publication_state` 状态行存在，但
`active_version=0`，`knowledge_publications` 记录数为 0。V2.1.5 因而只能保持
`candidate/pending_review`，不能晋升 Golden。人工审核通过后，还必须先获得可重放的
`knowledge_version > 0`；如果正式发布改变任何逻辑身份或 source revision，需要再派生
新数据集版本。

## 7. 人工审核清单

- [ ] 确认 Toon Case 的 5 个 Chunk 都直接回答能力边界，且不再需要背景总结 Chunk。
- [ ] 确认 Toon 权威来源各选一份 DOCX/PDF 主证据。
- [ ] 确认 Mover 迁移矩阵应计入语义相关，但不作为点名章节的权威来源。
- [ ] 确认 NNE 两个图文续块相关但不必全部强制命中。
- [ ] 确认 public 全文 16 个 qrels 中，12 个点名章节作为权威集合合理。
- [ ] 确认新增 `test_directory_mapping` 是问题要求的必要完整性事实。
- [x] 数据库服务恢复后已完成最终身份核对，48 个子块和 1 个父块验证通过。
- [ ] 确认未晋升 Golden 前不运行真实评测。

# RAG Eval 评测集 V2.1.4 Candidate 人工审核材料

## 1. 审核结论边界

本文件用于人工审核，不代表真实 RAG 评测已经执行，也不代表数据集已经晋升
Golden。V2.1.4 是从不可变的 V2.1.3 派生的新 Candidate；V2.1.3 未被原地修改。

- 数据集：`src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.4.json`
- 构建脚本：`.tmp/build_eval_dataset_v2_1_4.py`
- 离线契约测试：`scripts/tests/evaluation/test_eval_dataset_v2_1_4.py`
- `dataset_version`：`2.1.4`
- `lifecycle`：`candidate`
- Case：16 条（Reader 13 条，Operator 3 条）
- `knowledge_version`：0
- `source_revision`：`sha256:720ba93c1fa2f14d4da554921d0cd14a3e1d130c699fd2d641449f05600e0167`
- `content_sha256`：`b3b59273d57baaa5afae6219c1590041ec2d1a49c95f2fcb4b190f84ecea6618`
- 标注状态：全部 `pending_review`

构建脚本连续执行两次时，文件 SHA-256 和 `content_sha256` 均保持一致。

## 2. 本轮为什么必须建立 V2.1.4

V2.1.3 的第二轮复核发现 7 条 Case 存在标注语义问题。问题不在检索公式，
而在“问题范围、相关 Chunk 集合和 K 值”没有完全对齐。如果直接运行评测，会把
正确结果误算成 false positive，或让 Recall@K 在数学上不可能达到 1。

本轮按以下原则修正：

1. 问题问到的每个事实都必须能在 qrels 中找到直接证据。
2. 计为相关的每个 Chunk 必须直接帮助回答该问题。
3. 对 answerable Case，相关身份数量不能大于 `top_k`。
4. Underfilled Case 不能只标少量 qrels、再把同一限定文档内的其他相关结果算成噪声。
5. ACL 负例必须在授权身份下确实可回答，才能把无权身份的拒答归因于权限隔离。
6. 同一来源内出现冲突事实时，不用它构造需要唯一数值答案的 Case。

## 3. 七条修正 Case

### 3.1 `reader_longdocs_toon_production_multi_source`

问题改为：

> 两份 UE5.8.1 长手册都说明官方 Toon 不能自动完成 Anime Character Pipeline。
> 它已经提供哪些基础能力，项目仍需自行补齐哪些角色渲染模块？

相关 Chunk 收敛为 4 个，`top_k=5`：

- DOCX：`chunk_6f31fe460a4ff15b`、`chunk_e6d54817043b7a3e`
- PDF：`chunk_519c11634c2ef350`、`chunk_6fb6c9494ea6327d`

修正原因：V2.1.3 有 6 个相关 Chunk，但 `top_k=5`，因此 Recall@5 最多只能达到
5/6；原问题还混入生产路线、Experimental 风险和 fallback 等更宽主题，容易产生
漏标。本版本只评测两份长文档共同明确回答的“已有能力/缺失模块”。

### 3.2 `reader_public_acl_underfilled`

问题改为概述限定 public 文档的全文章节；保持精确 `source_path`、`top_k=20`、
`candidate_k=20`。当前该文档只有 16 个子块，因此 16 个子块全部列为相关 qrels。

完整 qrels：

`chunk_a96818cd638bdf5e`、`chunk_0d712ae8b17bbe30`、
`chunk_5b810cc8195b5051`、`chunk_1d4b9388b6b6a450`、
`chunk_9db8266b4400b809`、`chunk_46184d5a7c6d3eb2`、
`chunk_ab6631bbb6b4315e`、`chunk_30679008b2e6d98b`、
`chunk_f6a70fdc86583e29`、`chunk_34746fe25e2b2d22`、
`chunk_308b696cf3ecd8cd`、`chunk_0d557c0bdaaed986`、
`chunk_9306991da46132c3`、`chunk_aa8db320ce8941f2`、
`chunk_f9fff42f4d54189d`、`chunk_013212d0fb835c38`。

修正原因：V2.1.3 的问题只标 2 个相关块，但精确过滤后的 16 个块中有多个也能帮助
回答，导致 Precision 被标注结构性压低。现在“全文概述”与“全部 16 块均相关”一致，
同时仍然保留 16 < 20 的真实 underfilled 条件。

### 3.3 `reader_art_acl_negative`

问题改为：

> art 部门内部测试关键词列表是否同时包含“月光披风规则”和“女巫帽轮廓标准”？

- forbidden Chunk：`chunk_36c26dd9a52eeb3d`

修正原因：V2.1.3 问两个词“分别是什么”，但该 Chunk 只是列出关键词，授权用户也
无法解释它们分别是什么。新问题只询问是否存在；授权用户可明确回答“是”，
development Reader 不可见时才应拒答，因此权限变量被单独隔离。

### 3.4 `operator_pptx_network_strategy`

此 Case 替换 V2.1.3 的 `operator_pptx_input_buffer`。

新问题：

> 战斗系统 PPT 第 8 节规定客户端预测、服务端权威和回滚修正分别负责什么，
> 延迟测试使用哪些 PktLag 与 PacketLoss 档位？

- 精确来源：`docs/knowledge-base-acl-test/product_planning/UE5战斗系统设计方案_RAG测试用PPT.pptx`
- 相关 Chunk：`chunk_074e7c6fc05a33ef`

修正原因：旧 Case 对应 Chunk 的可见正文写 `0.18~0.28`，Notes 仍有旧值
`0.15-0.25`，不适合构造唯一数值答案。新 Case 使用无冲突的第 8 节，评测客户端
预测、服务端权威、回滚以及 `PktLag=80/150/250`、`PacketLoss=1%/3%`。

### 3.5 `reader_pdf_companion_ai_guard`

问题收窄到回归手册第 7.5 节的 Companion 执行链、非法动作 Guard 和模型不可用
fallback。

- `chunk_1aacfb4570bf0fbe`
- `chunk_5237f6b9758968d7`

修正原因：原问题覆盖整个 AI 分层，宏观总结块也可能相关。限定 7.5 节后，两个连续
跨页 Chunk 完整覆盖所问事实，减少“未标但相关”的歧义。

### 3.6 `reader_pdf_nne_training_runtime`

问题明确限定第 7.3～7.4 节和图 7-2，相关 Chunk 为：

- `chunk_fa9d79af16538c98`
- `chunk_dfec29f8331e1bd6`
- `chunk_c80e0436eac5de05`
- `chunk_1aacfb4570bf0fbe`
- `chunk_d8f7f46961b5a99e`

修正原因：V2.1.3 遗漏了 Learning Agents 跨页块以及 NNE Runtime 图像文本块。
本版本补齐直接证据，5 个 qrels 正好等于 `top_k=5`。

### 3.7 `reader_pdf_mover_migration`

问题明确限定第 8.1 节和第 10.1 节，相关 Chunk 为：

- `chunk_00499a8f184e0ffd`
- `chunk_50f5a64967ad9d11`
- `chunk_0c20779a4e397e0d`

修正原因：原问题还会让迁移矩阵和全书总结块成为合理相关结果。新问题只审核
“正式项目如何选择 CMC/Mover”以及“CMC 过时为何是误判”，证据边界更清晰。

## 4. 完整 Case 清单

| Case | 评测身份 | K | 相关身份数量 | 主要证据/边界 |
|---|---|---:|---:|---|
| `reader_word_face_outline_debugging` | Reader | 5 | 3 | DOCX Face SDF、Outline、单变量调试 |
| `reader_word_six_week_acceptance` | Reader | 5 | 2 | DOCX 六周计划与最低验收 |
| `reader_pdf_companion_ai_guard` | Reader | 5 | 2 | PDF 7.5 执行链与 fallback |
| `reader_pdf_nne_training_runtime` | Reader | 5 | 5 | PDF 7.3～7.4 与图 7-2 |
| `reader_pdf_mover_migration` | Reader | 5 | 3 | PDF 8.1 与 10.1 |
| `reader_pdf_performance_workflow` | Reader | 5 | 4 | PDF 帧预算、定位、回归、优化 |
| `reader_longdocs_toon_production_multi_source` | Reader | 5 | 4 | DOCX + PDF 的 Toon 能力边界 |
| `reader_deployment_env_parent_expansion` | Reader | 5 | 1 个逻辑父块 | 两个触发子块扩展至 `parent_8203549515f66e1b` |
| `reader_xlsx_perfect_block_asset` | Reader | 5 | 1 | XLSX AST-0022 精确行 |
| `reader_combat_perfect_block` | Reader | 5 | 1 | development Markdown 精确章节 |
| `reader_public_acl_underfilled` | Reader | 20 | 16 | 精确 public 文档全文，确定性 underfilled |
| `reader_art_acl_negative` | Reader | 5 | 0；1 个 forbidden | art 私有关键词不得泄漏 |
| `reader_no_result_wwise_audio` | Reader | 5 | 0 | 当前语料无 Wwise/AEC/Profiler 规则 |
| `operator_art_pixel_sprite` | Operator | 5 | 1 | 合法跨部门读取 art |
| `operator_product_skill_definition` | Operator | 5 | 1 | 合法跨部门读取 product_planning |
| `operator_pptx_network_strategy` | Operator | 5 | 1 | PPT 第 8 节无冲突网络策略 |

其余 9 条 Case 的问题语义和 qrels 未发生实质变化；V2.1.4 只重置了新版本身份和
待审核字段。

## 5. 数据库只读核对结果

V2.1.4 最终共引用 46 个子块（包含 answerable qrels 与 ACL forbidden Chunk）和
1 个父块：

- Elasticsearch：47/47 存在。
- Milvus：46/46 子块存在。
- 标注与 Elasticsearch 的 `doc_id`、`source_revision`、`source_path` 差异：0。
- 标注与 Milvus 的上述来源身份差异：0。
- Elasticsearch 与 Milvus 的上述来源身份差异：0。

该检查只验证身份、存在性和来源一致性，不等于检索排序或生成效果测试。

## 6. 自动门禁

`scripts/tests/evaluation/test_eval_dataset_v2_1_4.py` 当前覆盖：

- V2.1.3 内容哈希不变，V2.1.4 必须是独立 Candidate。
- 16 条 Case、13 Reader/3 Operator、9 份文档和 5 种格式保持完整。
- 所有 answerable Case 的相关身份数量不超过 `top_k`。
- 16 子块 underfilled qrels 契约。
- ACL 负例的授权可回答性语义。
- PPT 冲突 Case 已被无冲突 Case 替换。
- Companion、NNE、Mover 的章节范围和 qrels 精确契约。
- 必需场景矩阵仍然完整。

离线测试不会调用 RAG、Embedding、Reranker 或 DeepEval Judge。

## 7. 发布和 Golden 边界

PostgreSQL 当前正式知识版本仍为 0。现有 Schema 禁止将知识版本 0 的 Case 标记为
`approved` 或晋升 Golden。即使本次人工语义审核通过，也必须先通过正式发布流程
获得可重放的 `knowledge_version > 0`。

若正式发布后逻辑 Chunk ID、父块 ID、doc_id 或 source_revision 改变，必须再创建
新数据集版本，不能原地修改 V2.1.4。

## 8. 人工审核清单

- [ ] 确认 16 条问题都符合真实用户可能提出的问法。
- [ ] 确认 7 条修正 Case 的问题范围与 qrels 直接对应。
- [ ] 确认多来源 Toon Case 的 4 个 qrels 足以覆盖“已有能力/缺失模块”。
- [ ] 确认 public 全文概述允许把 16 个限定文档子块全部计为相关。
- [ ] 确认 ACL 负例应只问两个内部关键词是否同时存在。
- [ ] 确认用 PPT 第 8 节网络策略替换冲突输入缓存 Case。
- [ ] 确认 NNE Case 包含图 7-2 的图像文本块是合理标注。
- [ ] 确认 Mover Case 只评测 8.1 与 10.1，不要求迁移矩阵。
- [ ] 确认父块 Case 按逻辑父块身份计分。
- [ ] 确认人工审核和可重放知识版本准备完成前不运行真实评测。

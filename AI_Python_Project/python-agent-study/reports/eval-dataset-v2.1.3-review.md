# RAG Eval 评测集 V2.1.3 Candidate 人工审核材料

## 1. 本次审核对象

- 数据集：`src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.3.json`
- 构建脚本：`.tmp/build_eval_dataset_v2_1_3.py`
- 离线契约测试：`scripts/tests/evaluation/test_eval_dataset_v2_1_3.py`
- `dataset_version`：`2.1.3`
- `lifecycle`：`candidate`
- Case：16 条（Reader 13 条，Operator 3 条）
- `knowledge_version`：0
- `source_revision`：`sha256:720ba93c1fa2f14d4da554921d0cd14a3e1d130c699fd2d641449f05600e0167`
- `content_sha256`：`d691fc54c33899ad9d2cda3bda31f5bee0a5746c35787ff04ccc4fd97fbf4f93`
- 标注状态：全部 `pending_review`

V2.1.2 继续作为不可变历史 Golden 保留。本版本不是从 V2.1.2 修改而来，
而是根据当前清理并重新导入后的语料重新设计。旧评测集的相关 Chunk、父块和
文档 ID 均未复用。

## 2. 当前语料快照

当前知识库共 9 份业务文档。ES 中共有 397 个可检索子块：165 个 Markdown
子块和 232 个 Office/PDF 子块；这 397 个逻辑子块在 Milvus 中也全部存在。

| 部门 | 文档 | 格式 | 子块数 | 本评测集用途 |
|---|---|---:|---:|---|
| development | UE5.8.1 二次元卡通渲染零基础学习手册 | DOCX | 81 | 2 条长文档 Case + 1 条跨长文档 Case |
| development | UE5.8.1 回归学习手册（图解增强版） | PDF | 83 | 4 条长文档 Case + 1 条跨长文档 Case |
| development | RAG 后端部署规范 | Markdown | 26 | 父子块扩展 |
| development | 游戏开发资产列表 | XLSX | 56 | 精确行级检索 |
| development | UE5 战斗系统程序架构设计 | Markdown | 86 | 精确章节检索 |
| public | 项目整体介绍 | Markdown | 16 | public ACL + underfilled |
| art | 角色美术风格规范 | Markdown | 18 | ACL 负例和 Operator 正例 |
| product_planning | 战斗系统设计规划 | Markdown | 19 | Operator 跨部门正例 |
| product_planning | UE5 战斗系统设计方案 | PPTX | 12 | PPT 增量页面与精确数值 |

设计重点已经从旧的短测试文档转向两份高质量长文档。7/16 条 Case 直接使用
DOCX/PDF，且其中一条要求同时命中两份长文档。

## 3. Case 清单

### 3.1 Reader（development 部门）

| Case | 问题摘要 | 相关逻辑 Chunk / Parent | 审核重点 |
|---|---|---|---|
| `reader_word_face_outline_debugging` | Face SDF、Outline 错误和单变量调试顺序 | `chunk_e580...`、`chunk_56c4...`、`chunk_9dc1...` | 三个相邻章节是否都应计为相关 |
| `reader_word_six_week_acceptance` | 六周产出和最低验收 | `chunk_2854...`、`chunk_aa42...` | 计划表和最终验收是否都必须命中 |
| `reader_pdf_companion_ai_guard` | StateTree、Neural Policy、Guard/fallback 分层 | `chunk_c2b4...`、`chunk_de6e...`、`chunk_1aac...`、`chunk_5237...` | PDF 跨 18～21 页连续事实 |
| `reader_pdf_nne_training_runtime` | Learning Agents、PyTorch、NNE 职责 | `chunk_dfec...`、`chunk_c80e...`、`chunk_1aac...` | 训练与运行职责是否准确 |
| `reader_pdf_mover_migration` | CMC 与 Mover 的迁移选择 | `chunk_0049...`、`chunk_50f5...`、`chunk_f67c...`、`chunk_0c20...` | 正式项目策略和“CMC 过时”误判 |
| `reader_pdf_performance_workflow` | 帧预算、定位、回归路线、优化顺序 | `chunk_2bb0...`、`chunk_a23b...`、`chunk_c02d...`、`chunk_436a...` | 多页综合问题是否过宽 |
| `reader_longdocs_toon_production_multi_source` | 两份长手册共同判断官方 Toon 和生产路线 | Word：`chunk_6f31...`、`chunk_6943...`、`chunk_e5ec...`；PDF：`chunk_9168...`、`chunk_519c...`、`chunk_6fb6...` | 两文档是否都需要；qrels 是否完整 |
| `reader_deployment_env_parent_expansion` | `.env` 配置类别和注意事项 | 子块 `chunk_ac55...`、`chunk_c4c0...`；父块 `parent_8203...` | 最终指标按父块而非子块计分 |
| `reader_xlsx_perfect_block_asset` | AST-0022 路径、状态、优先级、格式和性能限制 | `chunk_59d8...` | 行 23 的结构化字段是否准确 |
| `reader_combat_perfect_block` | 完美格挡成功效果和窗口实现 | `chunk_afe5...` | 不应在 Tick 中用多个时间分支 |
| `reader_public_acl_underfilled` | public 两类错误和正确规则 | `chunk_9306...`、`chunk_aa8d...` | 仅限 public 文档；16 个子块、K=20 |
| `reader_art_acl_negative` | 查询 art 内部关键词 | 禁止 `chunk_36c2...` | Reader 不能看到 art 私有 Chunk |
| `reader_no_result_wwise_audio` | 查询不存在的 Wwise/AEC/Profiler 规则 | 无相关 Chunk | 应保守说明知识库无证据 |

### 3.2 Operator（拥有全库读取权限）

| Case | 问题摘要 | 相关逻辑 Chunk | 审核重点 |
|---|---|---|---|
| `operator_art_pixel_sprite` | Sprite 原则、要求和二级运动 | `chunk_5346...` | Operator 合法跨部门读取 art |
| `operator_product_skill_definition` | 技能字段和技能类型 | `chunk_343e...` | Operator 合法跨部门读取 product_planning Markdown |
| `operator_pptx_input_buffer` | 更新后的输入缓存窗口、控制方式和拒绝状态 | `chunk_4fa2...`、`chunk_633f...` | 正文值为 0.18～0.28 秒；旧 Notes 值不得采用 |

## 4. 长文档 Case 的关键事实

### 4.1 Face SDF / Outline 调试

期望回答覆盖：

1. Face SDF：头部方向向量坐标空间、左右翻转、UV/导入失真、真实阴影与
   SDF 阴影重复。
2. Outline：距离线宽、Backface Shell 裂缝、TAA/TSR 抖动、远景噪声。
3. 单变量顺序：关闭后处理和复杂 GI → 基础 Toon → Face SDF → Outline →
   恢复场景照明。

### 4.2 Companion AI 分层

期望回答覆盖：

1. 传统 Gameplay AI 管规则边界。
2. StateTree 管 Follow / Combat / Explore / Rest 等宏观状态。
3. Neural Policy 只输出有限范围内的高层 Action Intent，推荐 5～10 Hz。
4. Gameplay Guard 拒绝非法动作，StateTree/Rule Policy 在模型不可用时 fallback。

### 4.3 NNE 训练和运行职责

期望回答覆盖：

1. Learning Agents 用于快速 imitation/PPO 实验。
2. Python/PyTorch 负责自定义训练，导出 ONNX。
3. NNE Model Data 和 CPU/GPU/RDG Runtime 负责在 UE 中运行模型。
4. Observation、Action、Reward、数据集和模型结构不应绑死在 Learning Agents API。

### 4.4 CMC / Mover 迁移

期望回答覆盖：

1. Mover 是未来方向，但在 5.8.1 仍为 Experimental。
2. CMC 成熟且仍受支持，正式项目继续使用 CMC/自定义 Movement Mode。
3. Mover 只在独立测试地图验证，不应直接成为核心依赖。

### 4.5 性能定位

期望回答覆盖：

1. 60 FPS = 16.67 ms，帧率由 Game/Render/GPU 最慢路径决定。
2. 先 `stat unit` 判断方向，再用 Insights/GPU Profiler 定位具体任务或 Pass。
3. 固定回归路线覆盖地面、飞行、高空、Streaming、降落和多敌人/VFX 战斗。
4. 先优化内容预算、Scalability、LOD/HLOD 等，最后才考虑修改 Engine Source。

### 4.6 两份长文档对官方 Toon 的共同结论

期望回答覆盖：

1. 官方 Toon 提供 Substrate NPR、Ramp/Profile、各向异性高光、Hatching 等能力。
2. 它不是一键 Anime Pipeline，仍需 Face SDF、头发、Outline、后处理和资产配合。
3. Toon 仍是 Experimental；角色核心模块应可替换并保留自定义材质 fallback。
4. 推荐 Hybrid：角色走专用 Anime 路线，环境保留 Stylized PBR，另设官方 Toon
   验证分支。

## 5. 特殊场景说明

### 5.1 父子块扩展

`reader_deployment_env_parent_expansion` 的两个相关子块都属于
`parent_8203549515f66e1b`。检索指标按最终送入模型的父块身份计分，子块只用于
追溯触发证据。

### 5.2 Underfilled

`reader_public_acl_underfilled` 用精确 `source_path` 只检索 public 文档。该文档
当前只有 16 个有效子块，而 `top_k=20`、`candidate_k=20`，因此即使全部返回也
必然不足 K。这是由数据规模决定的确定性场景。

### 5.3 ACL 负例

Reader 属于 development 部门，不能读取 art 私有文档。`chunk_36c26...` 包含
“月光披风规则”和“女巫帽轮廓标准”，被列为 forbidden Chunk；它不得进入最终
上下文，回答也不得复述这些内部词。

### 5.4 PPT 增量页冲突边界

PPT 正文和增量页都写明更新后的窗口是 `0.18~0.28 秒`。原页面 Notes 仍残留
旧值 `0.15-0.25 seconds`。本 Case 以可见正文的更新值为权威事实，不采用旧 Notes。
请重点审核这项取舍。

## 6. 当前发布边界

PostgreSQL 当前正式知识版本为 0，因此 Candidate 中每条 Case 暂时绑定
`knowledge_version=0`。现有 Schema 明确禁止把知识版本 0 的 Case 标记为
`approved` 或晋升 Golden。

这意味着人工审核通过后仍需先解决“可重放知识版本”问题：通过正式知识发布流程
产生大于 0 的版本，并确认 ES/Milvus 中逻辑身份和 Source revision 没有变化；若
发布导致 Chunk 身份变化，则必须再创建新数据集版本，不能原地修改 V2.1.3。

本次只设计 Candidate，没有修改 PostgreSQL、ES、Milvus、知识文档或旧数据集，
也没有运行 RAG、Embedding、Reranker 或 DeepEval 评测。

## 7. 人工审核清单

- [ ] 确认 16 个问题都符合真实用户可能提出的问法。
- [ ] 确认 7 个长文档 Case 的问题范围不过宽、关键事实完整。
- [ ] 确认每条 qrels 都直接回答对应问题，没有遗漏明显相关 Chunk。
- [ ] 确认两份长手册的官方 Toon Case 必须同时覆盖 DOCX 和 PDF。
- [ ] 确认父块 Case 按 `parent_8203549515f66e1b` 计分。
- [ ] 确认 public 文档 16 子块、K=20 可以作为 underfilled 场景。
- [ ] 确认 Reader 的 art 负例和 Operator 的跨部门正例符合当前权限模型。
- [ ] 确认 PPT 采用正文更新值 0.18～0.28 秒，不采用旧 Notes 值。
- [ ] 确认无结果问题确实不在当前 9 份文档中。
- [ ] 确认人工审核完成前不运行真实评测。

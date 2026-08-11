# 评测集 V2.1.0 Candidate 人工审核材料（第4步）

- 状态：candidate（待人工审核晋升 golden）
- 文件：`src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.0.json`
- content_sha256：`f1967310c6ad10b01f635196487209c94e1852a9691be9ed5c262ed86a547116`
- source_revision：`sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`（knowledge_version=6）
- annotated_by：`lingma-agent:v2.1-candidate-builder`
- 构建脚本：`.tmp/build_eval_dataset_v2_1.py`（重跑可复现相同哈希）
- 旧数据集 `stage11_rag_eval_cases.v2.0.0.json` 原样保留，未改动。

## 1. Case 清单（15 条）

| # | case_id | 身份 | 问句 | 黄金 chunk | 场景标签 |
|---|---|---|---|---|---|
| 1 | reader_ue5_damage_formula_parent | reader | UE5 战斗系统中最终生命伤害的计算公式 | 2 个（chunk_7cb94aed146a6d3b、chunk_84348081c94edf87） | answerable, parent_expansion, underfilled_k |
| 2 | reader_ue5_perfect_block | reader | UE5 战斗系统设计中完美格挡成功后的效果与时间窗口控制方式 | 1 个（chunk_2d0790c48f8b0092） | answerable, parent_expansion |
| 3 | reader_gitlab_rollback_multi_source | reader | 知识库文档发布出问题需要回滚时的正确回滚方式 | 2 个（chunk_296a2380e2d87791、chunk_bb13f7442fb8745c） | answerable, multiple_relevant_sources |
| 4 | reader_webhook_worker_multi_source | reader | GitLab MR 合并后文档发布任务是如何处理的？ | 2 个（chunk_dea252b8024f71e1、chunk_0452d406311e7d7b） | answerable, multiple_relevant_sources |
| 5 | reader_milvus_index_check | reader | RAG 后端文档导入后检查 Milvus collection 需要确认哪些内容？ | 1 个（chunk_4e797af9683c05c2） | answerable |
| 6 | reader_art_acl_negative | reader | 角色美术规范里的月光披风规则和女巫帽轮廓标准具体是怎么定义的？ | 无（forbidden×2） | unanswerable, permission_filter |
| 7 | reader_visibility_positive | reader | 权限过滤规则中 development 用户应能检索到哪些文档，以及不应检索到哪些文档？ | 2 个（chunk_f8a53eabbef5743c、chunk_e61f024c79efd70d） | answerable, permission_filter, multiple_relevant_sources |
| 8 | reader_incremental_input_buffer | reader | 增量更新验收规则中输入缓存窗口的建议值 | 1 个（chunk_fbbecbe7a07925ba） | answerable |
| 9 | reader_unanswerable_audio_middleware | reader | 知识库中是否有关于 Wwise 音频中间件 Profiler 接入战斗系统性能分析的资料？ | 无 | unanswerable |
| 10 | reader_checklist_env_single_gold | reader | 本地部署 RAG 后端时的数据库迁移命令与迁移后需要确认的表（top_k=8） | 1 个（chunk_7dafc7207a61cc2e） | answerable, underfilled_k |
| 11 | reader_worker_failure_recovery | reader | 知识发布任务 Worker 失败后的恢复处理方式 | 1 个（chunk_bf7e323eb34c4674） | answerable |
| 12 | reader_no_result_backup_schedule | reader | 知识库文档冷备策略的执行时间与备份文件存放的存储桶位置 | 无 | unanswerable, no_result |
| 13 | operator_pixel_sprite_rules | operator | 角色美术规范中像素 Sprite 的制作核心原则与制作要求 | 1 个（chunk_a2a894bca15c2988） | answerable |
| 14 | operator_art_visible_scope_multi | operator | 在 ACL 权限测试中 art 部门用户应该能检索到哪些文档？ | 2 个（chunk_15eb212207bbd84e、chunk_9ca728a00b73727c） | answerable, permission_filter, multiple_relevant_sources |
| 15 | operator_dev_acl_negative | operator | 知识库中是否有关于 RAG 后端部署环境变量要求与 FastAPI 本地启动命令的资料？ | 无（forbidden） | unanswerable, permission_filter |

场景矩阵覆盖 7 个必选标签：answerable、unanswerable、permission_filter、parent_expansion、multiple_relevant_sources、no_result、underfilled_k（构建脚本含自检）。

关键事实（required_key_facts）均带权重；次要事实（如 central_service/window_control/notify_state/inspect_first）已降为非 critical，避免把检索弱相关分支误判为硬门禁失败。

## 2. 试跑结果汇总（candidate 最终哈希 f1967310…）

### reader 全量（reports\rag-eval-v21-reader-final2）

- 11/12 evaluated，1 条为概率性路由降级（见第4节风险①）
- recall 均值 0.875（8/8 通过）、hit_rate 1.0、mrr 0.781
- `reader_milvus_index_check` 单独复跑（reports\rag-eval-v21-milvus3）：recall=1.0 通过

### operator 全量（reports\rag-eval-v21-operator-final2）

- 3/3 evaluated
- recall 均值 0.75（2/2 通过）、hit_rate 1.0

### 单 case 修复复验报告

| 报告目录 | 内容 |
|---|---|
| reports\rag-eval-v21-visibility2 | reader_visibility_positive 问法修复后 recall=0.50 |
| reports\rag-eval-v21-visibility | operator_art_visible_scope_multi recall=0.50 + reader 修复前 recall=0 |
| reports\rag-eval-v21-milvus3 | reader_milvus_index_check recall=1.0 |

15 条 case 全部验证过进入正确路由（simple_rag -> knowledge_retrieval）且检索指标有效。

## 3. 本阶段工程修复（已生效）

1. **runner golden 门禁加 allow_candidate**（`src/fast_app/rag_eval/runner.py`）：candidate 数据集可试跑；正式回归测试仍走 `load_golden_eval_dataset`，门禁不变。CLI（`scripts/run_streaming_rag_eval.py`）按数据集 lifecycle 自动传入。
2. **snapshot 逻辑身份字段兼容**（`src/fast_app/evaluation/pipeline/snapshot_capture.py`）：真实写入链路存 `logical_record_id`，snapshot 原先只读历史 mock 键名 `logical_chunk_id`，导致检索指标恒为 0；已兼容两键。

## 4. 已知系统性风险（审核时须知）

1. **Router LLM 概率性波动**：任何 case 有小概率被降级为 `clarification_required`（router_low_confidence，阈值 0.75）或误判 decomposition。实证：`reader_milvus_index_check` 同一问句两次澄清、复跑通过（recall=1.0）。回归时遇到单条 route_mismatch 应先复跑确认，不要立即判定数据集问题。
2. **Precision@K 天然偏低**：黄金 chunk 仅 1-2 个而 top_k=5-8，precision 0.2-0.4 未过 0.5 阈值属预期，不代表检索失败（Recall/HitRate 才是主指标）。
3. **多来源 case 的 recall=0.5**：两个黄金 chunk 语义相近时 rerank 只保其一（如两条可见性 case），属检索能力现状而非标注错误；如需 recall=1.0 需后续改进检索链路，不是数据集问题。

## 5. 晋升 golden 操作说明（由用户执行）

1. 人工核对第 1 节清单：问句、黄金 chunk、场景标签、关键事实是否符合业务预期。
2. 审核通过后修改数据集文件：
   - `lifecycle`: `candidate` → `golden`
   - `review_status`: `pending_review` → `approved`（case 级）
   - 补充 `reviewed_by`：必须与 annotated_by `lingma-agent:v2.1-candidate-builder` 不同的真实审核人标识
   - 重算 `content_sha256`（可用构建脚本的 seal 逻辑或等价脚本；sha256 覆盖除自身外的全部数据集内容）
3. 晋升后验证：`scripts/tests/evaluation/test_eval_dataset_v2.py`（load_golden_eval_dataset 门禁）应能通过加载。
4. 第5步 rag_agent 链路验收（用户已确认只验收 rag_agent；classic / langgraph 不纳入）在 golden 状态下执行。

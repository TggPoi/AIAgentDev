# 评测集 V2.1.1 Candidate 人工审核材料

- 状态：candidate（待人工审核晋升 golden）
- 文件：`src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.1.json`
- content_sha256：`d6fbf555a86a391a74d97ecec2f03b73c563bd2ed169fe8ae96c76592933406b`
- source_revision：`sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- knowledge_version：6
- 构建脚本：`.tmp/build_eval_dataset_v2_1_1.py`
- V2.1.0 candidate 与对应历史试跑报告保持不变；V2.1.1 尚未运行 RAG 系统评测。

## 1. 修正结论

V2.1.1 根据 PostgreSQL、Elasticsearch、Milvus 的只读交叉审核修正 7 条 case：

1. 用父块正文显著长于子块的真实记录替换无效 `parent_expansion` 样例。
2. 普通完美格挡 case 删除无实际增益的 `parent_expansion` 标签。
3. 回滚 case 删除与当前数据库结构冲突的旧 SQL 回滚来源。
4. reader 的 art ACL 负例改为询问隐藏 Chunk 确实包含的测试关键词。
5. `underfilled_k` 改为使用只有一个有效子块的 source_path 过滤条件。
6. operator 的 art 范围 case 改为评测“文档如何描述普通 art 用户”，不再冒充该身份的 ACL 执行事实。
7. operator 的 development 负例改为 `knowledge:read:all` 跨部门读取正例。

## 2. Case 清单（15 条）

| # | case_id | 身份 | 问句 | 黄金/禁止 Chunk | 场景标签 |
|---|---|---|---|---|---|
| 1 | `reader_es_milvus_parent_child_expansion` | reader | 部署验收中 ES 父子块和 Milvus 子块分别如何存储并校验关联完整性？ | 黄金 `chunk_d26c5a41d92d12dd`；父块 `parent_19d48d66c7b9141e` | answerable, parent_expansion |
| 2 | `reader_ue5_perfect_block` | reader | UE5 战斗系统设计中完美格挡成功后的效果与时间窗口控制方式 | 黄金 `chunk_2d0790c48f8b0092` | answerable |
| 3 | `reader_gitlab_rollback_authoritative` | reader | 知识库文档发布出问题需要回滚时的正确回滚方式 | 黄金 `chunk_296a2380e2d87791` | answerable |
| 4 | `reader_webhook_worker_multi_source` | reader | GitLab MR 合并后文档发布任务是如何处理的？ | 黄金 `chunk_dea252b8024f71e1`、`chunk_0452d406311e7d7b` | answerable, multiple_relevant_sources |
| 5 | `reader_milvus_index_check` | reader | RAG 后端文档导入后检查 Milvus collection 需要确认哪些内容？ | 黄金 `chunk_4e797af9683c05c2` | answerable |
| 6 | `reader_art_acl_negative` | reader | 角色美术规范是否包含“月光披风规则”和“女巫帽轮廓标准”这两个内部测试关键词？ | 禁止 `chunk_0aa1bbea341cfb4d` | unanswerable, permission_filter |
| 7 | `reader_visibility_positive` | reader | 权限过滤规则中 development 用户应能检索到哪些文档，以及不应检索到哪些文档？ | 黄金 `chunk_f8a53eabbef5743c`、`chunk_e61f024c79efd70d` | answerable, permission_filter, multiple_relevant_sources |
| 8 | `reader_incremental_input_buffer` | reader | 增量更新验收规则中输入缓存窗口的建议值 | 黄金 `chunk_fbbecbe7a07925ba` | answerable |
| 9 | `reader_unanswerable_audio_middleware` | reader | 知识库中是否有关于 Wwise 音频中间件 Profiler 接入战斗系统性能分析的资料？ | 无 | unanswerable |
| 10 | `reader_agent_tool_acceptance_underfilled` | reader | Agent Tool Acceptance 文档用于哪个阶段的 HTTP 验收？ | 黄金 `chunk_321a5c310d96c5a9` | answerable, underfilled_k |
| 11 | `reader_worker_failure_recovery` | reader | 知识发布任务 Worker 失败后的恢复处理方式 | 黄金 `chunk_bf7e323eb34c4674` | answerable |
| 12 | `operator_pixel_sprite_rules` | operator | 角色美术规范中像素 Sprite 的制作核心原则与制作要求 | 黄金 `chunk_a2a894bca15c2988` | answerable |
| 13 | `operator_documented_art_scope_multi` | operator | ACL 规则文档如何描述普通 art 部门用户可见和不可见的文档范围？ | 黄金 `chunk_15eb212207bbd84e`、`chunk_9ca728a00b73727c` | answerable, multiple_relevant_sources |
| 14 | `operator_global_reader_dev_positive` | operator | 知识库中是否有关于 RAG 后端部署环境变量要求与 FastAPI 本地启动命令的资料？ | 黄金 `chunk_bf5a29d90fe09980`、`chunk_4280ef8844cf5af5` | answerable, permission_filter |
| 15 | `reader_no_result_backup_schedule` | reader | 知识库文档冷备策略的执行时间与备份文件存放的存储桶位置 | 无 | unanswerable, no_result |

场景矩阵继续覆盖 Golden 所需的 7 个标签：answerable、unanswerable、permission_filter、parent_expansion、multiple_relevant_sources、no_result、underfilled_k。

## 3. 数据库审核依据

- V2.1.1 引用的全部黄金/禁止 Chunk 均存在于知识版本 6 的当前有效记录中。
- Elasticsearch 与 Milvus 的 doc_id、正文、source_revision 和 ACL 一致。
- 对应文档与 PostgreSQL `gitlab_documents` 的路径、revision、ACL 和 active 状态一致。
- `reader_es_milvus_parent_child_expansion` 的命中子块只有章节标题，ES 父块包含完整的 801 字检查内容。
- `reader_agent_tool_acceptance_underfilled` 使用 `source_path=development/agent-tool-acceptance.md`；该文档当前只有 1 个有效子块，而 top_k=8。
- reader 只有 development 部门读取权限；operator 具有全局 `knowledge:read:all`。
- 当前有效 Markdown 子块中不存在 Wwise/Profiler/音频中间件以及冷备/备份/存储桶相关证据。

## 4. 审核与后续验收边界

V2.1.0 的历史报告使用哈希 `f1967310...`，不能作为 V2.1.1 的试跑或验收证据。

V2.1.1 当前只完成静态数据和三库一致性审核。人工批准前保持 candidate；批准后还需要分别以 reader/operator 身份执行新的 rag_agent 真实流式评测，并生成绑定 `d6fbf555...` 的新报告。

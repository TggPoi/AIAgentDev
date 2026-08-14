# RAG Eval V2.1.2 阶段一检索评测中文汇总

## 1. 评测身份

- 数据集：`stage11_acl_rag_eval@2.1.2`
- 生命周期：`golden`
- 数据集哈希：`71bb897a278b6501067d33e6e7aff933e56d4aa3ece8567d5f3343d0bb34ec7d`
- 知识版本：6
- Provider：`rag_agent`
- 模式：`retrieval`
- 被测模型：`qwen:qwen3.7-plus`
- DeepEval Judge：未启动

阶段一使用 Reader 和 Operator 两个真实身份分别运行，以保证认证用户、Case
身份和 ACL 一致。两轮正式报告是两个独立原子 Run，不能合并成同一个 Run ID。

## 2. 正式报告

### Reader

- Run ID：`48c67654-1754-4394-82c4-519b96b29858`
- Case：12/12 执行，失败 0，跳过 0
- 路由：12/12 均为 `simple_rag -> knowledge_retrieval`
- 指标错误：0
- 报告状态：`partial`
- 报告内耗时：850335.93 ms，约 14 分 10 秒
- JSON：`reports/rag-eval-v212-golden-stage1-reader-retrieval/rag-eval-rag_agent-48c67654-1754-4394-82c4-519b96b29858.json`
- Markdown：`reports/rag-eval-v212-golden-stage1-reader-retrieval/rag-eval-rag_agent-48c67654-1754-4394-82c4-519b96b29858.md`

### Operator

- Run ID：`afc65bad-7792-439c-b662-7fd358f4129c`
- Case：3/3 执行，失败 0，跳过 0
- 路由：3/3 均为 `simple_rag -> knowledge_retrieval`
- 指标错误：0
- 报告状态：`partial`
- 报告内耗时：296036.69 ms，约 4 分 56 秒
- JSON：`reports/rag-eval-v212-golden-stage1-operator-retrieval/rag-eval-rag_agent-afc65bad-7792-439c-b662-7fd358f4129c.json`
- Markdown：`reports/rag-eval-v212-golden-stage1-operator-retrieval/rag-eval-rag_agent-afc65bad-7792-439c-b662-7fd358f4129c.md`

两轮正式评测合计约 19 分 6 秒。此前 4 条高风险试跑另耗时约 6 分 31 秒，
试跑 Run ID 为 `5c75fba7-2d0f-46ad-a8f3-247ea2f0d6d1`。

## 3. 四项检索指标

| 身份 | Recall@K | Precision@K | HitRate@K | MRR |
|---|---:|---:|---:|---:|
| Reader（9 条可回答 Case） | 0.9278 | 0.4815 | 1.0000 | 0.9444 |
| Operator（3 条可回答 Case） | 0.8333 | 0.2667 | 1.0000 | 0.7778 |
| 加权汇总（12 条可回答 Case） | 0.9042 | 0.4278 | 1.0000 | 0.9028 |

Reader 的 3 条 no-answer Case 按指标契约跳过四项检索公式，不进入均值；它们仍然
完成真实路由、检索、ACL 和来源策略检查。

与 V2.1.1 旧 Reader 结果相比，V2.1.2 Reader 的 Recall 从 0.8889 提升到
0.9278，Precision 从 0.2889 提升到 0.4815，MRR 从 0.7222 提升到 0.9444，
HitRate 保持 1.0000。由于数据集标注语义和候选池代码都已经变化，这只能用于说明
修复方向有效，不能当作同一数据集上的严格基线差值。

## 4. `partial` 的准确含义

两轮报告均为 `partial`，但不存在 Case 执行失败、路由失败或指标计算错误。
`partial` 来自独立的检索来源策略失败：

1. `reader_gitlab_rollback_authoritative`
   - 已命中权威 Chunk `chunk_296a2380e2d87791`。
   - 同时检出两个禁止采用的旧 SQL 回滚 Chunk：
     `chunk_bb13f7442fb8745c`、`chunk_58906be3fa1f61ce`。
   - 这证明 Eval 已能独立暴露当前知识版本 6 的冲突知识风险。
2. `reader_webhook_worker_multi_source`
   - 缺失权威 Chunk `chunk_0452d406311e7d7b`、`chunk_dea252b8024f71e1`。
3. `reader_visibility_positive`
   - 命中 `chunk_f8a53eabbef5743c`，但缺失另一条指定权威来源
     `chunk_e61f024c79efd70d`。
4. `operator_documented_art_scope_multi`
   - 命中 `chunk_15eb212207bbd84e`，但缺失
     `chunk_9ca728a00b73727c`。

## 5. 未通过阈值的指标

Precision@K 阈值为 0.5，以下 Case 未通过：

- `reader_es_milvus_parent_child_expansion`：0.3333
- `reader_ue5_perfect_block`：0.2000
- `reader_milvus_index_check`：0.4000
- `reader_incremental_input_buffer`：0.2000
- `reader_worker_failure_recovery`：0.4000
- `operator_pixel_sprite_rules`：0.2000
- `operator_documented_art_scope_multi`：0.2000
- `operator_global_reader_dev_positive`：0.4000

`operator_global_reader_dev_positive` 的 MRR 为 0.3333，低于 0.5；其余可回答
Case 的 Recall、HitRate 和 MRR 均通过当前阈值。

这些低分表示最终 Top K 中仍有较多泛相关或噪声 Chunk，尤其是 Operator Case；
它们不再能简单归因于旧数据集漏标，需要结合本轮 Snapshot 继续逐 Case 分析排序、
语义边界和权威来源要求。

## 6. 修复验收结论

- 15/15 Case 均真实进入 `knowledge_retrieval`，没有 `route_mismatch`。
- Reader、Operator 身份与 ACL 均正常。
- `candidate_k` 候选池能够进入 reranker，最终结果再按请求 `top_k` 截断。
- underfilled Case 保持真实 1 条结果，没有补造候选。
- 父块 Case 按最终上下文的逻辑父块计分，Recall 和 MRR 均为 1.0。
- 语义相关指标与权威/禁止来源策略已经成功分离。
- 检索公式、来源策略和报告生成均无错误。
- Operator 的一个答案被 Prompt Guard 按敏感配置风险阻断，但其检索 Snapshot 完整，
  Case 仍正常完成检索指标计算；公开流式输出没有放行被阻断内容。

阶段一证明候选池和 Eval 判定修复已经生效，但同时确认生产知识冲突、部分权威来源
漏召回以及 Operator Precision/MRR 仍需后续处理。本报告不包含四个生成指标，也不
代表八指标最终基线。

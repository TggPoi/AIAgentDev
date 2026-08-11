# 轻量流式 RAG Eval 报告

- Run ID: `879decf6-5edb-4ce7-a956-a401c6ec38bf`
- Provider: `rag_agent`
- Status: `partial`
- Dataset: `stage11_acl_rag_eval@2.1.0`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `N/A`
- Cases: 12 (evaluated=10, failed=2, skipped=0)
- Duration: 578580.39 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 0.9286 | 7 | 7 | 3 | 0 | N/A |
| `retrieval_precision_at_k` | 0.2571 | 7 | 0 | 3 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 1.0000 | 7 | 7 | 3 | 0 | N/A |
| `retrieval_mrr` | 0.7500 | 7 | 6 | 3 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_ue5_damage_formula_parent` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 34724.39 |  |
| `reader_ue5_perfect_block` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 68876.72 |  |
| `reader_gitlab_rollback_multi_source` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 109015.89 |  |
| `reader_webhook_worker_multi_source` | failed | `question_decomposition -> no_knowledge_retrieval` | no | 6 | 50529.72 | route_mismatch: Golden 要求普通 RAG，但实际未进入顶层 knowledge_retrieval 路径 |
| `reader_milvus_index_check` | failed | `clarification_required -> no_knowledge_retrieval` | no | 6 | 15455.10 | route_mismatch: Golden 要求普通 RAG，但实际未进入顶层 knowledge_retrieval 路径 |
| `reader_art_acl_negative` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 23339.88 |  |
| `reader_visibility_positive` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 76600.71 |  |
| `reader_incremental_input_buffer` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 34306.86 |  |
| `reader_unanswerable_audio_middleware` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 23084.41 |  |
| `reader_checklist_env_single_gold` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 57649.98 |  |
| `reader_worker_failure_recovery` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 65011.08 |  |
| `reader_no_result_backup_schedule` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 19955.19 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `reader_ue5_damage_formula_parent` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_damage_formula_parent` | `retrieval_precision_at_k` | evaluated | 0.4000 | false | score=0.4000 < threshold=0.5000 |
| `reader_ue5_damage_formula_parent` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_damage_formula_parent` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_ue5_perfect_block` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_multi_source` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_multi_source` | `retrieval_precision_at_k` | evaluated | 0.4000 | false | score=0.4000 < threshold=0.5000 |
| `reader_gitlab_rollback_multi_source` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_multi_source` | `retrieval_mrr` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_art_acl_negative` | `retrieval_recall_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_art_acl_negative` | `retrieval_precision_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_art_acl_negative` | `retrieval_hit_rate_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_art_acl_negative` | `retrieval_mrr` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_visibility_positive` | `retrieval_recall_at_k` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_visibility_positive` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_visibility_positive` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_visibility_positive` | `retrieval_mrr` | evaluated | 0.2500 | false | score=0.2500 < threshold=0.5000 |
| `reader_incremental_input_buffer` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_incremental_input_buffer` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_unanswerable_audio_middleware` | `retrieval_recall_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_unanswerable_audio_middleware` | `retrieval_precision_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_unanswerable_audio_middleware` | `retrieval_hit_rate_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_unanswerable_audio_middleware` | `retrieval_mrr` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_checklist_env_single_gold` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_checklist_env_single_gold` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_checklist_env_single_gold` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_checklist_env_single_gold` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_mrr` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_no_result_backup_schedule` | `retrieval_recall_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_no_result_backup_schedule` | `retrieval_precision_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_no_result_backup_schedule` | `retrieval_hit_rate_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_no_result_backup_schedule` | `retrieval_mrr` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |

# 轻量流式 RAG Eval 报告

- Run ID: `f3278abe-bc75-485f-95ef-414502a8f603`
- Provider: `rag_agent`
- Status: `partial`
- Dataset: `stage11_acl_rag_eval@2.1.1`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `qwen3.7-max`
- Cases: 12 (evaluated=12, failed=0, skipped=0)
- Duration: 3481114.65 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 0.8889 | 9 | 9 | 3 | 0 | N/A |
| `retrieval_precision_at_k` | 0.2889 | 9 | 1 | 3 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 1.0000 | 9 | 9 | 3 | 0 | N/A |
| `retrieval_mrr` | 0.7222 | 9 | 7 | 3 | 0 | N/A |
| `generation_faithfulness` | 1.0000 | 9 | 9 | 0 | 3 | N/A |
| `generation_answer_relevance` | 0.8977 | 10 | 10 | 0 | 2 | N/A |
| `generation_answer_completeness` | 0.2857 | 7 | 2 | 3 | 2 | N/A |
| `generation_context_utilization` | 1.0000 | 10 | 10 | 0 | 2 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_es_milvus_parent_child_expansion` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 120086.66 |  |
| `reader_ue5_perfect_block` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 90026.19 |  |
| `reader_gitlab_rollback_authoritative` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 153045.48 |  |
| `reader_webhook_worker_multi_source` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 141994.25 |  |
| `reader_milvus_index_check` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 102242.76 |  |
| `reader_art_acl_negative` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 66263.69 |  |
| `reader_visibility_positive` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 53173.62 |  |
| `reader_incremental_input_buffer` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 47473.83 |  |
| `reader_unanswerable_audio_middleware` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 21096.06 |  |
| `reader_agent_tool_acceptance_underfilled` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 23714.79 |  |
| `reader_worker_failure_recovery` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 113602.90 |  |
| `reader_no_result_backup_schedule` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 25491.01 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `reader_es_milvus_parent_child_expansion` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_es_milvus_parent_child_expansion` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_es_milvus_parent_child_expansion` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_es_milvus_parent_child_expansion` | `retrieval_mrr` | evaluated | 0.2500 | false | score=0.2500 < threshold=0.5000 |
| `reader_es_milvus_parent_child_expansion` | `generation_faithfulness` | error | N/A | N/A | judge_invalid_output: Judge �޷����غϷ� JSON Schema �ṹ����� |
| `reader_es_milvus_parent_child_expansion` | `generation_answer_relevance` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_es_milvus_parent_child_expansion` | `generation_answer_completeness` | evaluated | 0.1000 | false | score=0.1000 < threshold=0.5000 |
| `reader_es_milvus_parent_child_expansion` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_ue5_perfect_block` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `generation_faithfulness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `generation_answer_relevance` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `generation_answer_completeness` | evaluated | 0.1000 | false | score=0.1000 < threshold=0.5000 |
| `reader_ue5_perfect_block` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_mrr` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `generation_faithfulness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `generation_answer_relevance` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `generation_answer_completeness` | evaluated | 0.1000 | false | score=0.1000 < threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_webhook_worker_multi_source` | `retrieval_recall_at_k` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_webhook_worker_multi_source` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_webhook_worker_multi_source` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_webhook_worker_multi_source` | `retrieval_mrr` | evaluated | 0.2500 | false | score=0.2500 < threshold=0.5000 |
| `reader_webhook_worker_multi_source` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 超过 300 秒 |
| `reader_webhook_worker_multi_source` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 超过 300 秒 |
| `reader_webhook_worker_multi_source` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 超过 300 秒 |
| `reader_webhook_worker_multi_source` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 超过 300 秒 |
| `reader_milvus_index_check` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_milvus_index_check` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_milvus_index_check` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_milvus_index_check` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_milvus_index_check` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 超过 300 秒 |
| `reader_milvus_index_check` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 超过 300 秒 |
| `reader_milvus_index_check` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 超过 300 秒 |
| `reader_milvus_index_check` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 超过 300 秒 |
| `reader_art_acl_negative` | `retrieval_recall_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_art_acl_negative` | `retrieval_precision_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_art_acl_negative` | `retrieval_hit_rate_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_art_acl_negative` | `retrieval_mrr` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_art_acl_negative` | `generation_faithfulness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_art_acl_negative` | `generation_answer_relevance` | evaluated | 0.7273 | true | score=0.7273 >= threshold=0.5000 |
| `reader_art_acl_negative` | `generation_answer_completeness` | skipped | N/A | N/A | no-answer case û�� required_key_facts |
| `reader_art_acl_negative` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_visibility_positive` | `retrieval_recall_at_k` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_visibility_positive` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_visibility_positive` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_visibility_positive` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_visibility_positive` | `generation_faithfulness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_visibility_positive` | `generation_answer_relevance` | evaluated | 0.7500 | true | score=0.7500 >= threshold=0.5000 |
| `reader_visibility_positive` | `generation_answer_completeness` | evaluated | 0.1000 | false | score=0.1000 < threshold=0.5000 |
| `reader_visibility_positive` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_incremental_input_buffer` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `generation_faithfulness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `generation_answer_relevance` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `generation_answer_completeness` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_unanswerable_audio_middleware` | `retrieval_recall_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_unanswerable_audio_middleware` | `retrieval_precision_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_unanswerable_audio_middleware` | `retrieval_hit_rate_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_unanswerable_audio_middleware` | `retrieval_mrr` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_unanswerable_audio_middleware` | `generation_faithfulness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_unanswerable_audio_middleware` | `generation_answer_relevance` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_unanswerable_audio_middleware` | `generation_answer_completeness` | skipped | N/A | N/A | no-answer case û�� required_key_facts |
| `reader_unanswerable_audio_middleware` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `retrieval_precision_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `generation_faithfulness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `generation_answer_relevance` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `generation_answer_completeness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_mrr` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `generation_faithfulness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `generation_answer_relevance` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `generation_answer_completeness` | evaluated | 0.1000 | false | score=0.1000 < threshold=0.5000 |
| `reader_worker_failure_recovery` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_no_result_backup_schedule` | `retrieval_recall_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_no_result_backup_schedule` | `retrieval_precision_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_no_result_backup_schedule` | `retrieval_hit_rate_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_no_result_backup_schedule` | `retrieval_mrr` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_no_result_backup_schedule` | `generation_faithfulness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_no_result_backup_schedule` | `generation_answer_relevance` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_no_result_backup_schedule` | `generation_answer_completeness` | skipped | N/A | N/A | no-answer case û�� required_key_facts |
| `reader_no_result_backup_schedule` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |

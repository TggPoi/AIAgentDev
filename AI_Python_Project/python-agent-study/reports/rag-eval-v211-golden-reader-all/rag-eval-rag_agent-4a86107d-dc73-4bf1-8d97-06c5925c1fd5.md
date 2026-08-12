# 轻量流式 RAG Eval 报告

- Run ID: `4a86107d-dc73-4bf1-8d97-06c5925c1fd5`
- Provider: `rag_agent`
- Status: `partial`
- Dataset: `stage11_acl_rag_eval@2.1.1`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `N/A`
- Cases: 12 (evaluated=11, failed=1, skipped=0)
- Duration: 3017475.35 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 0.8750 | 8 | 8 | 3 | 0 | N/A |
| `retrieval_precision_at_k` | 0.3000 | 8 | 1 | 3 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 1.0000 | 8 | 8 | 3 | 0 | N/A |
| `retrieval_mrr` | 0.7812 | 8 | 7 | 3 | 0 | N/A |
| `generation_faithfulness` | N/A | 0 | 0 | 0 | 11 | N/A |
| `generation_answer_relevance` | N/A | 0 | 0 | 0 | 11 | N/A |
| `generation_answer_completeness` | N/A | 0 | 0 | 0 | 11 | N/A |
| `generation_context_utilization` | N/A | 0 | 0 | 0 | 11 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_es_milvus_parent_child_expansion` | failed | `question_decomposition -> no_knowledge_retrieval` | no | 6 | 74683.15 | route_mismatch: Golden 要求普通 RAG，但实际未进入顶层 knowledge_retrieval 路径 |
| `reader_ue5_perfect_block` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 74779.39 |  |
| `reader_gitlab_rollback_authoritative` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 135599.10 |  |
| `reader_webhook_worker_multi_source` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 151673.53 |  |
| `reader_milvus_index_check` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 94718.78 |  |
| `reader_art_acl_negative` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 27353.35 |  |
| `reader_visibility_positive` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 70702.07 |  |
| `reader_incremental_input_buffer` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 26032.36 |  |
| `reader_unanswerable_audio_middleware` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 26883.53 |  |
| `reader_agent_tool_acceptance_underfilled` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 35647.81 |  |
| `reader_worker_failure_recovery` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 73296.24 |  |
| `reader_no_result_backup_schedule` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 21656.91 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `reader_ue5_perfect_block` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_ue5_perfect_block` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_ue5_perfect_block` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_ue5_perfect_block` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_ue5_perfect_block` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_gitlab_rollback_authoritative` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_mrr` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 超过 300 秒 |
| `reader_gitlab_rollback_authoritative` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 超过 300 秒 |
| `reader_gitlab_rollback_authoritative` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 超过 300 秒 |
| `reader_gitlab_rollback_authoritative` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 超过 300 秒 |
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
| `reader_art_acl_negative` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_art_acl_negative` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_art_acl_negative` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_art_acl_negative` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_visibility_positive` | `retrieval_recall_at_k` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_visibility_positive` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_visibility_positive` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_visibility_positive` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_visibility_positive` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_visibility_positive` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_visibility_positive` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_visibility_positive` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_incremental_input_buffer` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_incremental_input_buffer` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_incremental_input_buffer` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_incremental_input_buffer` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_incremental_input_buffer` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_unanswerable_audio_middleware` | `retrieval_recall_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_unanswerable_audio_middleware` | `retrieval_precision_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_unanswerable_audio_middleware` | `retrieval_hit_rate_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_unanswerable_audio_middleware` | `retrieval_mrr` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_unanswerable_audio_middleware` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_unanswerable_audio_middleware` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_unanswerable_audio_middleware` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_unanswerable_audio_middleware` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_agent_tool_acceptance_underfilled` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `retrieval_precision_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_agent_tool_acceptance_underfilled` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_agent_tool_acceptance_underfilled` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_agent_tool_acceptance_underfilled` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_worker_failure_recovery` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_mrr` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_worker_failure_recovery` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_worker_failure_recovery` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_worker_failure_recovery` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_no_result_backup_schedule` | `retrieval_recall_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_no_result_backup_schedule` | `retrieval_precision_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_no_result_backup_schedule` | `retrieval_hit_rate_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_no_result_backup_schedule` | `retrieval_mrr` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `reader_no_result_backup_schedule` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_no_result_backup_schedule` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_no_result_backup_schedule` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_no_result_backup_schedule` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |

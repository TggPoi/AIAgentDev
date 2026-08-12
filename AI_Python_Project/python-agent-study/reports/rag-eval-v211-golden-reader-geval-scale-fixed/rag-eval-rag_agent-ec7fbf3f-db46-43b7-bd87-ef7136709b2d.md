# 轻量流式 RAG Eval 报告

- Run ID: `ec7fbf3f-db46-43b7-bd87-ef7136709b2d`
- Provider: `rag_agent`
- Status: `completed`
- Dataset: `stage11_acl_rag_eval@2.1.1`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `qwen3.7-max`
- Cases: 12 (evaluated=12, failed=0, skipped=0)
- Duration: 1331866.05 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `generation_answer_completeness` | 0.9444 | 9 | 9 | 3 | 0 | N/A |
| `generation_context_utilization` | 0.9833 | 12 | 12 | 0 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_es_milvus_parent_child_expansion` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 98694.50 |  |
| `reader_ue5_perfect_block` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 58817.93 |  |
| `reader_gitlab_rollback_authoritative` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 139594.44 |  |
| `reader_webhook_worker_multi_source` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 130242.75 |  |
| `reader_milvus_index_check` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 106389.93 |  |
| `reader_art_acl_negative` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 34387.93 |  |
| `reader_visibility_positive` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 50970.62 |  |
| `reader_incremental_input_buffer` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 40694.96 |  |
| `reader_unanswerable_audio_middleware` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 27978.59 |  |
| `reader_agent_tool_acceptance_underfilled` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 32183.99 |  |
| `reader_worker_failure_recovery` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 139627.50 |  |
| `reader_no_result_backup_schedule` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 25069.44 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `reader_es_milvus_parent_child_expansion` | `generation_answer_completeness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_es_milvus_parent_child_expansion` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `generation_answer_completeness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_ue5_perfect_block` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `generation_answer_completeness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_webhook_worker_multi_source` | `generation_answer_completeness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_webhook_worker_multi_source` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_milvus_index_check` | `generation_answer_completeness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_milvus_index_check` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_art_acl_negative` | `generation_answer_completeness` | skipped | N/A | N/A | no-answer case û�� required_key_facts |
| `reader_art_acl_negative` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_visibility_positive` | `generation_answer_completeness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_visibility_positive` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `generation_answer_completeness` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_incremental_input_buffer` | `generation_context_utilization` | evaluated | 0.9000 | true | score=0.9000 >= threshold=0.5000 |
| `reader_unanswerable_audio_middleware` | `generation_answer_completeness` | skipped | N/A | N/A | no-answer case û�� required_key_facts |
| `reader_unanswerable_audio_middleware` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `generation_answer_completeness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `generation_answer_completeness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `generation_context_utilization` | evaluated | 0.9000 | true | score=0.9000 >= threshold=0.5000 |
| `reader_no_result_backup_schedule` | `generation_answer_completeness` | skipped | N/A | N/A | no-answer case û�� required_key_facts |
| `reader_no_result_backup_schedule` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |

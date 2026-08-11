# 轻量流式 RAG Eval 报告

- Run ID: `c58bdcba-8e01-4167-affc-f7414ac5c52a`
- Provider: `rag_agent`
- Status: `completed`
- Dataset: `stage11_acl_rag_eval@2.1.0`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `N/A`
- Cases: 4 (evaluated=4, failed=0, skipped=0)
- Duration: 305347.38 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 1.0000 | 4 | 4 | 0 | 0 | N/A |
| `retrieval_precision_at_k` | 0.2500 | 4 | 0 | 0 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 1.0000 | 4 | 4 | 0 | 0 | N/A |
| `retrieval_mrr` | 0.8750 | 4 | 4 | 0 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_gitlab_rollback_multi_source` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 60011.56 |  |
| `reader_milvus_index_check` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 110643.67 |  |
| `reader_checklist_env_single_gold` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 52767.59 |  |
| `reader_worker_failure_recovery` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 81914.83 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `reader_gitlab_rollback_multi_source` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_multi_source` | `retrieval_precision_at_k` | evaluated | 0.4000 | false | score=0.4000 < threshold=0.5000 |
| `reader_gitlab_rollback_multi_source` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_multi_source` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_milvus_index_check` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_milvus_index_check` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_milvus_index_check` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_milvus_index_check` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_checklist_env_single_gold` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_checklist_env_single_gold` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_checklist_env_single_gold` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_checklist_env_single_gold` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_worker_failure_recovery` | `retrieval_mrr` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |

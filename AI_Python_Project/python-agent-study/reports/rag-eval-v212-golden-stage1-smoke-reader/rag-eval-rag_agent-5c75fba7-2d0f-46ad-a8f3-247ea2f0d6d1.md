# 轻量流式 RAG Eval 报告

- Run ID: `5c75fba7-2d0f-46ad-a8f3-247ea2f0d6d1`
- Provider: `rag_agent`
- Status: `partial`
- Dataset: `stage11_acl_rag_eval@2.1.2`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `N/A`
- Cases: 4 (evaluated=4, failed=0, skipped=0)
- Duration: 391421.49 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 0.9000 | 4 | 4 | 0 | 0 | N/A |
| `retrieval_precision_at_k` | 0.6333 | 4 | 3 | 0 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 1.0000 | 4 | 4 | 0 | 0 | N/A |
| `retrieval_mrr` | 0.8750 | 4 | 4 | 0 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_es_milvus_parent_child_expansion` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 91316.52 |  |
| `reader_gitlab_rollback_authoritative` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 111519.96 |  |
| `reader_webhook_worker_multi_source` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 139290.44 |  |
| `reader_agent_tool_acceptance_underfilled` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 49285.30 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `reader_es_milvus_parent_child_expansion` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_es_milvus_parent_child_expansion` | `retrieval_precision_at_k` | evaluated | 0.3333 | false | score=0.3333 < threshold=0.5000 |
| `reader_es_milvus_parent_child_expansion` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_es_milvus_parent_child_expansion` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_precision_at_k` | evaluated | 0.6000 | true | score=0.6000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_mrr` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_webhook_worker_multi_source` | `retrieval_recall_at_k` | evaluated | 0.6000 | true | score=0.6000 >= threshold=0.5000 |
| `reader_webhook_worker_multi_source` | `retrieval_precision_at_k` | evaluated | 0.6000 | true | score=0.6000 >= threshold=0.5000 |
| `reader_webhook_worker_multi_source` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_webhook_worker_multi_source` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `retrieval_precision_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_agent_tool_acceptance_underfilled` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |

## 检索来源策略

| Case | Passed | Matched authoritative | Missing authoritative | Forbidden retrieved |
|---|---|---|---|---|
| `reader_es_milvus_parent_child_expansion` | true | parent_19d48d66c7b9141e | N/A | N/A |
| `reader_gitlab_rollback_authoritative` | false | chunk_296a2380e2d87791 | N/A | chunk_bb13f7442fb8745c, chunk_58906be3fa1f61ce |
| `reader_webhook_worker_multi_source` | false | N/A | chunk_0452d406311e7d7b, chunk_dea252b8024f71e1 | N/A |
| `reader_agent_tool_acceptance_underfilled` | true | chunk_321a5c310d96c5a9 | N/A | N/A |

# 轻量流式 RAG Eval 报告

- Run ID: `de770dbe-0cad-480c-8b20-1552df30baa9`
- Provider: `rag_agent`
- Status: `partial`
- Dataset: `stage11_acl_rag_eval@2.1.1`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `N/A`
- Cases: 1 (evaluated=1, failed=0, skipped=0)
- Duration: 387837.04 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 1.0000 | 1 | 1 | 0 | 0 | N/A |
| `retrieval_precision_at_k` | 0.2000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 1.0000 | 1 | 1 | 0 | 0 | N/A |
| `retrieval_mrr` | 0.5000 | 1 | 1 | 0 | 0 | N/A |
| `generation_faithfulness` | N/A | 0 | 0 | 0 | 1 | N/A |
| `generation_answer_relevance` | N/A | 0 | 0 | 0 | 1 | N/A |
| `generation_answer_completeness` | N/A | 0 | 0 | 0 | 1 | N/A |
| `generation_context_utilization` | N/A | 0 | 0 | 0 | 1 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_gitlab_rollback_authoritative` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 127638.58 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `reader_gitlab_rollback_authoritative` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `retrieval_mrr` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `reader_gitlab_rollback_authoritative` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_gitlab_rollback_authoritative` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_gitlab_rollback_authoritative` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |
| `reader_gitlab_rollback_authoritative` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: DeepEval Worker 返回了非法 JSON 协议 |

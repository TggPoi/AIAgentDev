# 轻量流式 RAG Eval 报告

- Run ID: `c779b5c7-2d23-4f34-aadd-8dbd5e7f58fa`
- Provider: `rag_agent`
- Status: `completed`
- Dataset: `stage11_acl_rag_eval@2.1.1`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `qwen3.7-max`
- Cases: 1 (evaluated=1, failed=0, skipped=0)
- Duration: 331343.68 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 0.0000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_precision_at_k` | 0.0000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 0.0000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_mrr` | 0.0000 | 1 | 0 | 0 | 0 | N/A |
| `generation_faithfulness` | 1.0000 | 1 | 1 | 0 | 0 | N/A |
| `generation_answer_relevance` | 1.0000 | 1 | 1 | 0 | 0 | N/A |
| `generation_answer_completeness` | 1.0000 | 1 | 1 | 0 | 0 | N/A |
| `generation_context_utilization` | 1.0000 | 1 | 1 | 0 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `operator_documented_art_scope_multi` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 103402.77 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `operator_documented_art_scope_multi` | `retrieval_recall_at_k` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `operator_documented_art_scope_multi` | `retrieval_precision_at_k` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `operator_documented_art_scope_multi` | `retrieval_hit_rate_at_k` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `operator_documented_art_scope_multi` | `retrieval_mrr` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `operator_documented_art_scope_multi` | `generation_faithfulness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_documented_art_scope_multi` | `generation_answer_relevance` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_documented_art_scope_multi` | `generation_answer_completeness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_documented_art_scope_multi` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |

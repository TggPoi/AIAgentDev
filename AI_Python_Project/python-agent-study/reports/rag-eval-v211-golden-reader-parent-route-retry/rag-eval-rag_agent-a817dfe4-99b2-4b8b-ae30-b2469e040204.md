# 轻量流式 RAG Eval 报告

- Run ID: `a817dfe4-99b2-4b8b-ae30-b2469e040204`
- Provider: `rag_agent`
- Status: `failed`
- Dataset: `stage11_acl_rag_eval@2.1.1`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `N/A`
- Cases: 1 (evaluated=0, failed=1, skipped=0)
- Duration: 63634.35 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | N/A | 0 | 0 | 0 | 0 | N/A |
| `retrieval_precision_at_k` | N/A | 0 | 0 | 0 | 0 | N/A |
| `retrieval_hit_rate_at_k` | N/A | 0 | 0 | 0 | 0 | N/A |
| `retrieval_mrr` | N/A | 0 | 0 | 0 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_es_milvus_parent_child_expansion` | failed | `question_decomposition -> no_knowledge_retrieval` | no | 6 | 63633.47 | route_mismatch: Golden 要求普通 RAG，但实际未进入顶层 knowledge_retrieval 路径 |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|

# 轻量流式 RAG Eval 报告

- Run ID: `4a8bbc40-f98c-4686-a86a-fbb2b587f1ba`
- Provider: `rag_agent`
- Status: `completed`
- Dataset: `stage11_acl_rag_eval@2.1.0`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `N/A`
- Cases: 1 (evaluated=1, failed=0, skipped=0)
- Duration: 106744.18 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 1.0000 | 1 | 1 | 0 | 0 | N/A |
| `retrieval_precision_at_k` | 0.2000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 1.0000 | 1 | 1 | 0 | 0 | N/A |
| `retrieval_mrr` | 1.0000 | 1 | 1 | 0 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_milvus_index_check` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 106741.38 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `reader_milvus_index_check` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_milvus_index_check` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_milvus_index_check` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_milvus_index_check` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |

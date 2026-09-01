# 轻量流式 RAG Eval 报告

- Run ID: `f9713a84-9df4-47fb-aaee-2458e6b77f8e`
- Provider: `rag_agent`
- Status: `failed`
- Dataset: `stage11_acl_rag_eval@2.1.6`
- Knowledge revision: `sha256:720ba93c1fa2f14d4da554921d0cd14a3e1d130c699fd2d641449f05600e0167`
- Tested model: `qwen:qwen3.7-plus-2026-05-26`
- Judge model: `N/A`
- Cases: 1 (evaluated=0, failed=1, skipped=0)
- Duration: 5261.09 ms

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
| `reader_public_acl_underfilled` | failed | `N/A` | no | N/A | 5260.45 | route_mismatch: Golden 要求普通 RAG，但实际未进入顶层 knowledge_retrieval 路径 |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|

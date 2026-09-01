# 轻量流式 RAG Eval 报告

- Run ID: `e50f18a1-de50-424e-82d4-0133ec24429b`
- Provider: `rag_agent`
- Status: `partial`
- Dataset: `stage11_acl_rag_eval@2.1.6`
- Knowledge revision: `sha256:720ba93c1fa2f14d4da554921d0cd14a3e1d130c699fd2d641449f05600e0167`
- Tested model: `qwen:qwen3.7-plus-2026-05-26`
- Judge model: `N/A`
- Cases: 1 (evaluated=1, failed=0, skipped=0)
- Duration: 88229.00 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 0.5000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_precision_at_k` | 0.2000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 1.0000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_mrr` | 1.0000 | 1 | 0 | 0 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_pdf_companion_ai_guard` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 0 | 88225.53 |  |

## 检索 K 与容量诊断

| Case | requested_k | effective_k | returned | Gold | Hits | Max Recall | Capacity limited | Underfilled |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `reader_pdf_companion_ai_guard` | 5 | 5 | 5 | 2 | 1 | 1.0000 | false | false |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `reader_pdf_companion_ai_guard` | `retrieval_recall_at_k` | evaluated | 0.5000 | N/A | score=0.5000; threshold=not_configured |
| `reader_pdf_companion_ai_guard` | `retrieval_precision_at_k` | evaluated | 0.2000 | N/A | score=0.2000; threshold=not_configured |
| `reader_pdf_companion_ai_guard` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | N/A | score=1.0000; threshold=not_configured |
| `reader_pdf_companion_ai_guard` | `retrieval_mrr` | evaluated | 1.0000 | N/A | score=1.0000; threshold=not_configured |

## 检索来源策略

| Case | Passed | Matched authoritative | Missing authoritative | Forbidden retrieved |
|---|---|---|---|---|
| `reader_pdf_companion_ai_guard` | false | chunk_5237f6b9758968d7 | chunk_1aacfb4570bf0fbe | N/A |

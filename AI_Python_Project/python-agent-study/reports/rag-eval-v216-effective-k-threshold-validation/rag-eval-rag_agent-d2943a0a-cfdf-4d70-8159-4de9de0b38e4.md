# 轻量流式 RAG Eval 报告

- Run ID: `d2943a0a-cfdf-4d70-8159-4de9de0b38e4`
- Provider: `rag_agent`
- Status: `partial`
- Dataset: `stage11_acl_rag_eval@2.1.6`
- Knowledge revision: `sha256:720ba93c1fa2f14d4da554921d0cd14a3e1d130c699fd2d641449f05600e0167`
- Tested model: `qwen:qwen3.7-plus-2026-05-26`
- Judge model: `N/A`
- Cases: 1 (evaluated=1, failed=0, skipped=0)
- Duration: 58263.66 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 1.0000 | 1 | 1 | 0 | 0 | N/A |
| `retrieval_precision_at_k` | 0.2000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 1.0000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_mrr` | 1.0000 | 1 | 0 | 0 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_xlsx_perfect_block_asset` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 0 | 58258.74 |  |

## 检索 K 与容量诊断

| Case | requested_k | effective_k | returned | Gold | Hits | Max Recall | Capacity limited | Underfilled |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `reader_xlsx_perfect_block_asset` | 5 | 5 | 5 | 1 | 1 | 1.0000 | false | false |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `reader_xlsx_perfect_block_asset` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `reader_xlsx_perfect_block_asset` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `reader_xlsx_perfect_block_asset` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | N/A | score=1.0000; threshold=not_configured |
| `reader_xlsx_perfect_block_asset` | `retrieval_mrr` | evaluated | 1.0000 | N/A | score=1.0000; threshold=not_configured |

## 检索来源策略

| Case | Passed | Matched authoritative | Missing authoritative | Forbidden retrieved |
|---|---|---|---|---|
| `reader_xlsx_perfect_block_asset` | true | chunk_59d89c39b0ad2fb6 | N/A | N/A |

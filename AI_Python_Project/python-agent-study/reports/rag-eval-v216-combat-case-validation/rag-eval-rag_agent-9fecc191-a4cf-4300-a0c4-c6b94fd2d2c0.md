# 轻量流式 RAG Eval 报告

- Run ID: `9fecc191-a4cf-4300-a0c4-c6b94fd2d2c0`
- Provider: `rag_agent`
- Status: `completed`
- Dataset: `stage11_acl_rag_eval@2.1.6`
- Knowledge revision: `sha256:720ba93c1fa2f14d4da554921d0cd14a3e1d130c699fd2d641449f05600e0167`
- Tested model: `qwen:qwen3.7-plus-2026-05-26`
- Judge model: `N/A`
- Cases: 1 (evaluated=1, failed=0, skipped=0)
- Duration: 63990.79 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 1.0000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_precision_at_k` | 0.2000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 1.0000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_mrr` | 1.0000 | 1 | 0 | 0 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_combat_perfect_block` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 0 | 63987.26 |  |

## 检索 K 与容量诊断

| Case | requested_k | effective_k | returned | Gold | Hits | Max Recall | Capacity limited | Underfilled |
|---|---:|---:|---:|---:|---:|---:|---|---|
| `reader_combat_perfect_block` | 5 | 5 | 5 | 1 | 1 | 1.0000 | false | false |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `reader_combat_perfect_block` | `retrieval_recall_at_k` | evaluated | 1.0000 | N/A | score=1.0000; threshold=not_configured |
| `reader_combat_perfect_block` | `retrieval_precision_at_k` | evaluated | 0.2000 | N/A | score=0.2000; threshold=not_configured |
| `reader_combat_perfect_block` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | N/A | score=1.0000; threshold=not_configured |
| `reader_combat_perfect_block` | `retrieval_mrr` | evaluated | 1.0000 | N/A | score=1.0000; threshold=not_configured |

## 检索来源策略

| Case | Passed | Matched authoritative | Missing authoritative | Forbidden retrieved |
|---|---|---|---|---|
| `reader_combat_perfect_block` | true | chunk_afe53a82b6a0d200 | N/A | N/A |

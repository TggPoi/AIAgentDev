# 轻量流式 RAG Eval 报告

- Run ID: `6f1bbadc-5b72-4f6d-9d17-9e91c7d98cc3`
- Provider: `rag_agent`
- Status: `partial`
- Dataset: `stage11_acl_rag_eval@2.1.6`
- Knowledge revision: `sha256:720ba93c1fa2f14d4da554921d0cd14a3e1d130c699fd2d641449f05600e0167`
- Tested model: `qwen:qwen3.7-plus-2026-05-26`
- Judge model: `N/A`
- Cases: 1 (evaluated=1, failed=0, skipped=0)
- Duration: 37184.35 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 0.0000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_precision_at_k` | 0.0000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 0.0000 | 1 | 0 | 0 | 0 | N/A |
| `retrieval_mrr` | 0.0000 | 1 | 0 | 0 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `reader_public_acl_underfilled` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 0 | 37180.66 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `reader_public_acl_underfilled` | `retrieval_recall_at_k` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `reader_public_acl_underfilled` | `retrieval_precision_at_k` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `reader_public_acl_underfilled` | `retrieval_hit_rate_at_k` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `reader_public_acl_underfilled` | `retrieval_mrr` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |

## 检索来源策略

| Case | Passed | Matched authoritative | Missing authoritative | Forbidden retrieved |
|---|---|---|---|---|
| `reader_public_acl_underfilled` | false | N/A | chunk_0d557c0bdaaed986, chunk_1d4b9388b6b6a450, chunk_30679008b2e6d98b, chunk_308b696cf3ecd8cd, chunk_34746fe25e2b2d22, chunk_5b810cc8195b5051, chunk_9306991da46132c3, chunk_9db8266b4400b809, chunk_aa8db320ce8941f2, chunk_ab6631bbb6b4315e, chunk_f6a70fdc86583e29, chunk_f9fff42f4d54189d | N/A |

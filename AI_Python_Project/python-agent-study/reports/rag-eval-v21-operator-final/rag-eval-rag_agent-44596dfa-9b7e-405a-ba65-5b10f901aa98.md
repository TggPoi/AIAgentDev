# 轻量流式 RAG Eval 报告

- Run ID: `44596dfa-9b7e-405a-ba65-5b10f901aa98`
- Provider: `rag_agent`
- Status: `completed`
- Dataset: `stage11_acl_rag_eval@2.1.0`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `N/A`
- Cases: 3 (evaluated=3, failed=0, skipped=0)
- Duration: 184947.98 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 0.5000 | 2 | 1 | 1 | 0 | N/A |
| `retrieval_precision_at_k` | 0.1000 | 2 | 0 | 1 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 0.5000 | 2 | 1 | 1 | 0 | N/A |
| `retrieval_mrr` | 0.5000 | 2 | 1 | 1 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `operator_pixel_sprite_rules` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 64771.98 |  |
| `operator_art_visible_scope_multi` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 58333.85 |  |
| `operator_dev_acl_negative` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 61835.65 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `operator_pixel_sprite_rules` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_pixel_sprite_rules` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `operator_pixel_sprite_rules` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_pixel_sprite_rules` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_art_visible_scope_multi` | `retrieval_recall_at_k` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `operator_art_visible_scope_multi` | `retrieval_precision_at_k` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `operator_art_visible_scope_multi` | `retrieval_hit_rate_at_k` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `operator_art_visible_scope_multi` | `retrieval_mrr` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `operator_dev_acl_negative` | `retrieval_recall_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `operator_dev_acl_negative` | `retrieval_precision_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `operator_dev_acl_negative` | `retrieval_hit_rate_at_k` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |
| `operator_dev_acl_negative` | `retrieval_mrr` | skipped | N/A | N/A | no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用 |

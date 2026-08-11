# 轻量流式 RAG Eval 报告

- Run ID: `7295c234-8dd2-4df4-a078-d949b5d64789`
- Provider: `rag_agent`
- Status: `partial`
- Dataset: `stage11_acl_rag_eval@2.1.0`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `N/A`
- Cases: 3 (evaluated=1, failed=2, skipped=0)
- Duration: 156419.18 ms

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
| `operator_pixel_sprite_rules` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 66312.96 |  |
| `operator_art_visible_scope_multi` | failed | `question_decomposition -> no_knowledge_retrieval` | no | 6 | 43867.39 | route_mismatch: Golden 要求普通 RAG，但实际未进入顶层 knowledge_retrieval 路径 |
| `operator_dev_acl_negative` | failed | `question_decomposition -> no_knowledge_retrieval` | no | 6 | 46235.76 | route_mismatch: Golden 要求普通 RAG，但实际未进入顶层 knowledge_retrieval 路径 |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `operator_pixel_sprite_rules` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_pixel_sprite_rules` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `operator_pixel_sprite_rules` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_pixel_sprite_rules` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |

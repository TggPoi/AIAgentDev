# 轻量流式 RAG Eval 报告

- Run ID: `afc65bad-7792-439c-b662-7fd358f4129c`
- Provider: `rag_agent`
- Status: `partial`
- Dataset: `stage11_acl_rag_eval@2.1.2`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `N/A`
- Cases: 3 (evaluated=3, failed=0, skipped=0)
- Duration: 296036.69 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 0.8333 | 3 | 3 | 0 | 0 | N/A |
| `retrieval_precision_at_k` | 0.2667 | 3 | 0 | 0 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 1.0000 | 3 | 3 | 0 | 0 | N/A |
| `retrieval_mrr` | 0.7778 | 3 | 2 | 0 | 0 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `operator_pixel_sprite_rules` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 89185.07 |  |
| `operator_documented_art_scope_multi` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 126147.90 |  |
| `operator_global_reader_dev_positive` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 80694.91 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `operator_pixel_sprite_rules` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_pixel_sprite_rules` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `operator_pixel_sprite_rules` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_pixel_sprite_rules` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_documented_art_scope_multi` | `retrieval_recall_at_k` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `operator_documented_art_scope_multi` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `operator_documented_art_scope_multi` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_documented_art_scope_multi` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_global_reader_dev_positive` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_global_reader_dev_positive` | `retrieval_precision_at_k` | evaluated | 0.4000 | false | score=0.4000 < threshold=0.5000 |
| `operator_global_reader_dev_positive` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_global_reader_dev_positive` | `retrieval_mrr` | evaluated | 0.3333 | false | score=0.3333 < threshold=0.5000 |

## 检索来源策略

| Case | Passed | Matched authoritative | Missing authoritative | Forbidden retrieved |
|---|---|---|---|---|
| `operator_pixel_sprite_rules` | true | chunk_a2a894bca15c2988 | N/A | N/A |
| `operator_documented_art_scope_multi` | false | chunk_15eb212207bbd84e | chunk_9ca728a00b73727c | N/A |
| `operator_global_reader_dev_positive` | true | chunk_bf5a29d90fe09980, chunk_4280ef8844cf5af5 | N/A | N/A |

# 轻量流式 RAG Eval 报告

- Run ID: `b1e1fba6-e999-4e6f-9e57-1ba499221785`
- Provider: `rag_agent`
- Status: `partial`
- Dataset: `stage11_acl_rag_eval@2.1.1`
- Knowledge revision: `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- Tested model: `qwen:qwen3.7-plus`
- Judge model: `qwen3.7-max`
- Cases: 3 (evaluated=3, failed=0, skipped=0)
- Duration: 889887.82 ms

## 指标汇总

| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |
|---|---:|---:|---:|---:|---:|---:|
| `retrieval_recall_at_k` | 0.5000 | 3 | 2 | 0 | 0 | N/A |
| `retrieval_precision_at_k` | 0.1333 | 3 | 0 | 0 | 0 | N/A |
| `retrieval_hit_rate_at_k` | 0.6667 | 3 | 2 | 0 | 0 | N/A |
| `retrieval_mrr` | 0.4444 | 3 | 1 | 0 | 0 | N/A |
| `generation_faithfulness` | 1.0000 | 2 | 2 | 0 | 1 | N/A |
| `generation_answer_relevance` | 1.0000 | 2 | 2 | 0 | 1 | N/A |
| `generation_answer_completeness` | 0.7500 | 2 | 2 | 0 | 1 | N/A |
| `generation_context_utilization` | 1.0000 | 2 | 2 | 0 | 1 | N/A |

## Case 明细

| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |
|---|---|---|---:|---:|---:|---|
| `operator_pixel_sprite_rules` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 70293.17 |  |
| `operator_documented_art_scope_multi` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 113818.21 |  |
| `operator_global_reader_dev_positive` | evaluated | `simple_rag -> knowledge_retrieval` | yes | 6 | 62254.66 |  |

## Case 指标明细

| Case | Metric | Status | Score | Passed | Reason / Error |
|---|---|---|---:|---|---|
| `operator_pixel_sprite_rules` | `retrieval_recall_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_pixel_sprite_rules` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `operator_pixel_sprite_rules` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_pixel_sprite_rules` | `retrieval_mrr` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_pixel_sprite_rules` | `generation_faithfulness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_pixel_sprite_rules` | `generation_answer_relevance` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_pixel_sprite_rules` | `generation_answer_completeness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_pixel_sprite_rules` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_documented_art_scope_multi` | `retrieval_recall_at_k` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `operator_documented_art_scope_multi` | `retrieval_precision_at_k` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `operator_documented_art_scope_multi` | `retrieval_hit_rate_at_k` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `operator_documented_art_scope_multi` | `retrieval_mrr` | evaluated | 0.0000 | false | score=0.0000 < threshold=0.5000 |
| `operator_documented_art_scope_multi` | `generation_faithfulness` | error | N/A | N/A | generation_worker_failed: 'utf-8' codec can't decode byte 0xd0 in position 264: invalid continuation byte |
| `operator_documented_art_scope_multi` | `generation_answer_relevance` | error | N/A | N/A | generation_worker_failed: 'utf-8' codec can't decode byte 0xd0 in position 264: invalid continuation byte |
| `operator_documented_art_scope_multi` | `generation_answer_completeness` | error | N/A | N/A | generation_worker_failed: 'utf-8' codec can't decode byte 0xd0 in position 264: invalid continuation byte |
| `operator_documented_art_scope_multi` | `generation_context_utilization` | error | N/A | N/A | generation_worker_failed: 'utf-8' codec can't decode byte 0xd0 in position 264: invalid continuation byte |
| `operator_global_reader_dev_positive` | `retrieval_recall_at_k` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `operator_global_reader_dev_positive` | `retrieval_precision_at_k` | evaluated | 0.2000 | false | score=0.2000 < threshold=0.5000 |
| `operator_global_reader_dev_positive` | `retrieval_hit_rate_at_k` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_global_reader_dev_positive` | `retrieval_mrr` | evaluated | 0.3333 | false | score=0.3333 < threshold=0.5000 |
| `operator_global_reader_dev_positive` | `generation_faithfulness` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_global_reader_dev_positive` | `generation_answer_relevance` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |
| `operator_global_reader_dev_positive` | `generation_answer_completeness` | evaluated | 0.5000 | true | score=0.5000 >= threshold=0.5000 |
| `operator_global_reader_dev_positive` | `generation_context_utilization` | evaluated | 1.0000 | true | score=1.0000 >= threshold=0.5000 |

# RAG Offline Evaluation Report

## Summary

| Field | Value |
| --- | --- |
| dataset | stage11_rag_eval_cases |
| case_count | 6 |
| response_count | 6 |
| retrieval_mean_recall_at_k | 0.0667 |
| retrieval_mean_mrr | 0.1000 |
| retrieval_passed | 1/5 |
| generation_pass_rate | 0.6667 |
| generation_passed | 4/6 |

## Retrieval Results

| Case | Passed | Recall@K | MRR | First Hit Rank | Hits |
| --- | --- | ---: | ---: | ---: | --- |
| phase9_hybrid_retrieval_basic | FAIL | 0.0000 | 0.0000 |  |  |
| phase9_metadata_sources | FAIL | 0.0000 | 0.0000 |  |  |
| phase9_lifespan_clients | PASS | 0.3333 | 0.5000 | 2 | chunk_6fbad71a519bd92b |
| phase9_stream_events | FAIL | 0.0000 | 0.0000 |  |  |
| phase9_fallback_policy | FAIL | 0.0000 | 0.0000 |  |  |

## Generation Results

| Case | Type | Passed | Answer Length | Source Count | Failed Checks |
| --- | --- | --- | ---: | ---: | --- |
| phase9_hybrid_retrieval_basic | answerable | PASS | 2076 | 5 |  |
| phase9_metadata_sources | answerable | PASS | 1636 | 5 |  |
| phase9_lifespan_clients | answerable | PASS | 1588 | 5 |  |
| phase9_stream_events | answerable | PASS | 2304 | 5 |  |
| phase9_fallback_policy | answerable | FAIL | 1975 | 5 | expected_keywords |
| no_answer_weather | no_answer | FAIL | 1570 | 5 | no_answer_refusal |

## Failed Generation Details

### phase9_fallback_policy

- question: RAG 链路中为什么需要 timeout、retry 和 fallback？
- case_type: answerable

- expected_keywords: 回答缺少预期关键词; detail={'expected_keywords': ['timeout', 'retry', 'fallback', '外部服务'], 'missing_keywords': ['外部服务']}

### no_answer_weather

- question: 明天北京天气怎么样？
- case_type: no_answer

- no_answer_refusal: 无答案问题没有明确拒答; detail={'refusal_markers': ['当前知识库中没有足够信息', '没有足够信息', '无法根据检索上下文'], 'matched_markers': []}

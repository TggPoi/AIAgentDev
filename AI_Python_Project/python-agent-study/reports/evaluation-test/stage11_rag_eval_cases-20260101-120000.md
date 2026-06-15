# RAG Offline Evaluation Report

## Summary

| Field | Value |
| --- | --- |
| dataset | stage11_rag_eval_cases |
| case_count | 6 |
| response_count | 6 |
| retrieval_mean_recall_at_k | 0.2000 |
| retrieval_mean_mrr | 0.2000 |
| retrieval_passed | 1/5 |
| generation_pass_rate | 0.1667 |
| generation_passed | 1/6 |

## Retrieval Results

| Case | Passed | Recall@K | MRR | First Hit Rank | Hits |
| --- | --- | ---: | ---: | ---: | --- |
| phase9_hybrid_retrieval_basic | PASS | 1.0000 | 1.0000 | 1 | demo_chunk |
| phase9_metadata_sources | FAIL | 0.0000 | 0.0000 |  |  |
| phase9_lifespan_clients | FAIL | 0.0000 | 0.0000 |  |  |
| phase9_stream_events | FAIL | 0.0000 | 0.0000 |  |  |
| phase9_fallback_policy | FAIL | 0.0000 | 0.0000 |  |  |

## Generation Results

| Case | Type | Passed | Answer Length | Source Count | Failed Checks |
| --- | --- | --- | ---: | ---: | --- |
| phase9_hybrid_retrieval_basic | answerable | PASS | 63 | 1 |  |
| phase9_metadata_sources | answerable | FAIL | 63 | 1 | expected_keywords |
| phase9_lifespan_clients | answerable | FAIL | 63 | 1 | expected_keywords |
| phase9_stream_events | answerable | FAIL | 63 | 1 | expected_keywords |
| phase9_fallback_policy | answerable | FAIL | 63 | 1 | expected_keywords |
| no_answer_weather | no_answer | FAIL | 63 | 1 | no_answer_refusal |

## Failed Generation Details

### phase9_metadata_sources

- question: 阶段 9 为什么要把 metadata 写入 ES 和 Milvus，并在 sources 中展示 title 和 section_path？
- case_type: answerable

- expected_keywords: 回答缺少预期关键词; detail={'expected_keywords': ['metadata', 'sources', 'title', 'section_path'], 'missing_keywords': ['metadata', 'sources', 'title', 'section_path']}

### phase9_lifespan_clients

- question: FastAPI lifespan 为什么适合管理 Milvus、ES 和 httpx client？
- case_type: answerable

- expected_keywords: 回答缺少预期关键词; detail={'expected_keywords': ['lifespan', 'client', '启动', '关闭'], 'missing_keywords': ['lifespan', 'client', '启动', '关闭']}

### phase9_stream_events

- question: 阶段 9 的 stream event 协议为什么要区分 token、sources、done 和 error？
- case_type: answerable

- expected_keywords: 回答缺少预期关键词; detail={'expected_keywords': ['token', 'sources', 'done', 'error'], 'missing_keywords': ['token', 'sources', 'done', 'error']}

### phase9_fallback_policy

- question: RAG 链路中为什么需要 timeout、retry 和 fallback？
- case_type: answerable

- expected_keywords: 回答缺少预期关键词; detail={'expected_keywords': ['timeout', 'retry', 'fallback', '外部服务'], 'missing_keywords': ['timeout', 'retry', 'fallback', '外部服务']}

### no_answer_weather

- question: 明天北京天气怎么样？
- case_type: no_answer

- no_answer_refusal: 无答案问题没有明确拒答; detail={'refusal_markers': ['当前知识库中没有足够信息', '没有足够信息', '无法根据检索上下文'], 'matched_markers': []}

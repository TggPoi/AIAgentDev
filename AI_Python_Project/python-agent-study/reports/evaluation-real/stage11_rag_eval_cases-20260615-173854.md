# RAG Offline Evaluation Report

## Summary

| Field | Value |
| --- | --- |
| dataset | stage11_rag_eval_cases |
| case_count | 6 |
| response_count | 6 |
| retrieval_mean_recall_at_k | 1.0000 |
| retrieval_mean_mrr | 0.5000 |
| retrieval_passed | 5/5 |
| generation_pass_rate | 0.6667 |
| generation_passed | 4/6 |

## Retrieval Results

| Case | Passed | Recall@K | MRR | First Hit Rank | Hits |
| --- | --- | ---: | ---: | ---: | --- |
| phase9_hybrid_retrieval_basic | PASS | 1.0000 | 0.5000 | 2 | chunk_432ca43648f041f8, chunk_3d67735cce7bc193, chunk_0b4355f8ce3cdece |
| phase9_metadata_sources | PASS | 1.0000 | 0.5000 | 2 | chunk_187c2c92f1fa0cf8, chunk_ffa6b354e74ea966 |
| phase9_lifespan_clients | PASS | 1.0000 | 0.5000 | 2 | chunk_98d4820c74801e18, chunk_1c7de21f5203b102 |
| phase9_stream_events | PASS | 1.0000 | 0.5000 | 2 | chunk_a1fa4d2e05b4a0ef, chunk_4d6adaf242dcbd83, chunk_6cf75131ea1faaac |
| phase9_fallback_policy | PASS | 1.0000 | 0.5000 | 2 | chunk_c62f6bc03854326e |

## Generation Results

| Case | Type | Passed | Answer Length | Source Count | Failed Checks |
| --- | --- | --- | ---: | ---: | --- |
| phase9_hybrid_retrieval_basic | answerable | PASS | 773 | 5 |  |
| phase9_metadata_sources | answerable | PASS | 664 | 5 |  |
| phase9_lifespan_clients | answerable | FAIL | 471 | 5 | expected_keywords, source_citation |
| phase9_stream_events | answerable | PASS | 558 | 5 |  |
| phase9_fallback_policy | answerable | FAIL | 652 | 5 | expected_keywords |
| no_answer_weather | no_answer | PASS | 19 | 5 |  |

## Failed Generation Details

### phase9_lifespan_clients

- question: FastAPI lifespan 为什么适合管理 Milvus、ES 和 httpx client？
- case_type: answerable

- expected_keywords: 回答缺少预期关键词; detail={'expected_keywords': ['lifespan', 'client', '启动', '关闭'], 'missing_keywords': ['启动']}
- source_citation: 回答没有引用 source id; detail={'source_ids': ['chunk_06b0a096584a5ee5', 'chunk_98d4820c74801e18', 'chunk_79508fe4d0238d2c', 'chunk_1c7de21f5203b102', 'chunk_7e41b30d137db3de'], 'cited_source_ids': []}

### phase9_fallback_policy

- question: RAG 链路中为什么需要 timeout、retry 和 fallback？
- case_type: answerable

- expected_keywords: 回答缺少预期关键词; detail={'expected_keywords': ['timeout', 'retry', 'fallback', '外部服务'], 'missing_keywords': ['外部服务']}

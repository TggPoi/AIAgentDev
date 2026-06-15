# RAG Evaluation

本目录用于保存 RAG 评测相关模型、评测集和后续评测逻辑。

## 当前阶段

阶段 11-2 只定义评测集和 loader。

当前不会执行真实 RAG 请求，也不会计算 Recall@K / MRR。

## 文件说明

```text
eval_case_models.py
```

定义评测集的数据结构。

```text
eval_dataset_loader.py
```

读取 JSON 评测集，并用 Pydantic 校验字段。

```text
datasets/stage11_rag_eval_cases.json
```

阶段 11 使用的小型 RAG 问答评测集。

## 字段说明

`case_type` 表示样例类型：

```text
answerable：知识库应该能回答
no_answer：知识库不应该给出确定答案
```

`question` 是用户问题。

`mode` 和 `/rag/chat` 的 `mode` 一致：

```text
vector
keyword
hybrid
```

`top_k` 表示最终返回 sources 的数量上限。

`candidate_k` 表示每个召回源的候选数量。

`filters` 表示 metadata 过滤条件，结构和 `RagChatRequest.filters` 一致。

`expected_sources` 表示期望命中的来源线索。

`expected_answer_keywords` 表示回答中应该出现的关键词。

`forbidden_answer_keywords` 表示回答中不应该出现的关键词。

## 检索评测指标

阶段 11-3 增加纯函数指标计算。

当前指标包括：

```text
Recall@K
```

前 K 个检索结果中命中的预期来源比例。

```text
MRR
```

第一个正确命中结果排名倒数的平均值。

```text
first_hit_rank
```

第一个正确结果出现的位置。

```text
matched_by
```

说明命中依据，例如：

```text
chunk_id
source_path
section_keywords
```

当前只对 `answerable` 样例计算检索指标。

`no_answer` 样例主要用于后续生成评测。

## Milvus 向量召回评测

阶段 11-4 增加 Milvus 单路向量召回评测。

核心流程：

```text
RagEvalCase
-> RetrievalOptions
-> MilvusVectorRetriever.retrieve()
-> RetrievedDoc list
-> evaluate_retrieval_case()
-> RetrievalCaseResult
```

注意：

- 写入 Milvus 的 embedding 和评测查询的 embedding 必须一致。
- `candidate_k` 是 Milvus 查询候选数。
- `top_k` 是参与 Recall@K / MRR 的最终文档数量。
- 当前阶段只评测 `answerable` 样例。

## ElasticSearch 关键词召回评测

阶段 11-5 增加 ElasticSearch 单路关键词召回评测。

核心流程：

```text
RagEvalCase
-> RetrievalOptions
-> ElasticsearchKeywordRetriever.retrieve()
-> RetrievedDoc list
-> evaluate_retrieval_case()
-> RetrievalCaseResult
```

注意：

- `candidate_k` 是 ES 查询候选数。
- `top_k` 是参与 Recall@K / MRR 的最终文档数量。
- ES `_score` 只代表关键词检索相关性，不能直接和 Milvus vector score 比大小。
- 当前 ES 查询主要 match `content` 字段。
- 当前阶段只评测 `answerable` 样例。

## Hybrid 对比实验

阶段 11-6 增加 vector / keyword / RRF / rerank 对比。

对比对象：

```text
vector
```

Milvus 单路向量召回。

```text
keyword
```

ElasticSearch 单路关键词召回。

```text
rrf
```

vector + keyword 的 RRF 融合结果。

```text
rerank
```

RRF 结果再经过 reranker。

重点观察：

```text
mean_recall_at_k
mean_mrr
passed_case_count
failed_case_count
```

注意：

- RRF 主要观察两路召回是否互补。
- rerank 主要观察正确结果是否被排到更前。
- rerank 不能找回没有进入候选集的文档。

## 本地校验

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -c "from fast_app.evaluation.eval_dataset_loader import load_eval_dataset; dataset = load_eval_dataset('src/fast_app/evaluation/datasets/stage11_rag_eval_cases.json'); print(dataset.name, len(dataset.cases))"
```

检索指标纯函数校验：

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -c "from fast_app.evaluation.eval_dataset_loader import load_eval_dataset; from fast_app.evaluation.retrieval_metrics import evaluate_retrieval_case; from fast_app.domain.rag_models import RetrievedDoc; dataset = load_eval_dataset('src/fast_app/evaluation/datasets/stage11_rag_eval_cases.json'); case = dataset.cases[0]; docs = [RetrievedDoc(id='demo', content='这里包含 vector_score keyword_score rrf_score rerank_score 和 RRF rerank', score=0.9, source='mock', title='score demo', metadata={'section_path':['RRF rerank score'], 'source_path':'demo.md'})]; result = evaluate_retrieval_case(case, docs); print(result.case_id, result.recall_at_k, result.reciprocal_rank, result.passed)"
```

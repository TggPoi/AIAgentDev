# RAG Evaluation

本目录用于保存 RAG 评测相关模型、评测集和后续评测逻辑。

## 目录说明

```text
cases/
```

保存评测集数据结构和 dataset loader。

```text
retrieval/
```

保存检索评测结果模型、Recall@K / MRR 指标、Milvus 单路评测、ElasticSearch 单路评测、Hybrid / RRF / rerank 对比评测。

```text
generation/
```

保存规则型生成评测结果模型和生成指标计算。

```text
pipeline/
```

保存离线 RAG pipeline runner 和完整评测报告模型。

```text
reports/
```

保存 JSON / Markdown 报告序列化、渲染和写入逻辑。

```text
thresholds/
```

保存评测阈值检查逻辑，用于日常回归。

```text
datasets/stage11_rag_eval_cases.json
datasets/stage11_rag_eval_cases.v2.candidate.json
datasets/stage11_rag_eval_cases.v2.0.0.json
```

第一个文件是只读兼容用的 legacy fixture；第二个文件保留阶段 11-13 的模型辅助候选标注；第三个文件是经过人工批准、可进入正式质量门禁的不可变 V2 Golden 基线。

## V2 数据集契约

V2 用 `case_id`、`dataset_version`、`knowledge_version` 和 `source_revision` 固定一次可重放评测。检索相关性使用稳定的 `logical_chunk_ids` 与 `logical_doc_id`，父块来源必须记录 `matched_logical_child_ids`。答案完整性标注使用带 `weight` 和 `critical` 的 `required_key_facts`。

`eval_principal_id` 只引用服务端评测身份，不能在数据集 `filters` 中注入部门或用户 ACL。`candidate` 可以包含待审核标注；`golden` 要求所有 case 都由人工批准，并覆盖可回答、不可回答、权限过滤、父块扩展、多来源、无结果和结果不足 K 场景。

旧数据由 loader 显式迁移为 `legacy_migration` candidate，不能直接冒充 Golden。正式执行应使用 `load_golden_eval_dataset()`；内容哈希、版本、身份、事实权重和跨字段约束不合法时会拒绝加载。

## Legacy 字段说明

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

## 生成评测指标

阶段 11-7 增加规则型生成评测。

当前检查项：

```text
expected_keywords
```

answer 是否覆盖预期关键词。

```text
forbidden_keywords
```

answer 是否出现禁止关键词。

```text
no_answer_refusal
```

无答案问题是否明确拒答。

```text
source_presence
```

answerable 样例是否返回 sources。

```text
source_citation
```

answer 是否引用了 sources 中的 id。

当前生成评测不调用 LLM-as-judge。

它只基于 `RagEvalCase` 和 `RagChatResponse` 做可解释规则检查。

## 离线 RAG 评测 Runner

阶段 11-8 增加批量请求 pipeline 的离线评测入口。

核心流程：

```text
RagEvalDataset
-> RagChatRequest
-> pipeline.run(req)
-> RagChatResponse
-> RetrievalDatasetReport
-> GenerationDatasetReport
-> OfflineRagEvalReport
```

当前 runner 只要求 pipeline 提供 `run(req)` 方法。

因此 Classic Pipeline 和 LangGraph Pipeline 都可以复用。

## 评测报告输出

阶段 11-9 增加 Markdown / JSON 报告输出。

JSON 用于程序读取和后续自动对比。

Markdown 用于人工阅读和排查失败 case。

默认输出目录：

```text
reports/evaluation
```

文件名格式：

```text
{dataset_name}-{YYYYMMDD-HHMMSS}.json
{dataset_name}-{YYYYMMDD-HHMMSS}.md
```

## 日常修改流程

阶段 11-10 增加阈值检查和日常回归流程。

修改 RAG 主链路前：

1. 使用真实离线评测脚本生成 baseline 报告。
2. 记录 Markdown 报告路径。

修改 RAG 主链路后：

1. 使用同一份评测集、同一组参数再次运行脚本。
2. 对比 Summary 中的 retrieval / generation 指标。
3. 查看 Failed Generation Details。
4. 如果阈值检查失败，先分析失败 case，再继续改代码。

建议至少在修改这些内容后运行评测：

- chunking
- metadata
- Milvus / ES 查询参数
- RRF
- rerank
- Prompt
- LLM model
- Classic / LangGraph pipeline

带阈值检查的命令示例：

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe scripts\run_real_offline_rag_eval.py `
  --llm-provider qwen `
  --embedding-provider mock `
  --reranker-provider mock `
  --pipeline-provider classic `
  --output-dir reports\evaluation-real `
  --min-retrieval-recall 0.2 `
  --min-retrieval-mrr 0.1 `
  --min-generation-pass-rate 0.2 `
  --fail-on-threshold
```

阈值含义：

```text
--min-retrieval-recall：最低 mean_recall_at_k
--min-retrieval-mrr：最低 mean_mrr
--min-generation-pass-rate：最低 generation pass_rate
--fail-on-threshold：任一阈值失败时返回退出码 1
```

## 本地校验

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -c "from fast_app.evaluation.cases.loader import load_golden_eval_dataset; dataset = load_golden_eval_dataset('src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.0.0.json'); print(dataset.name, dataset.dataset_version, len(dataset.cases))"
```

检索指标纯函数校验：

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -c "from fast_app.evaluation.cases.loader import load_eval_dataset; from fast_app.evaluation.retrieval.metrics import evaluate_retrieval_case; from fast_app.domain.rag_models import RetrievedDoc; dataset = load_eval_dataset('src/fast_app/evaluation/datasets/stage11_rag_eval_cases.json'); case = dataset.cases[0]; docs = [RetrievedDoc(id='demo', content='这里包含 vector_score keyword_score rrf_score rerank_score 和 RRF rerank', score=0.9, source='mock', title='score demo', metadata={'section_path':['RRF rerank score'], 'source_path':'demo.md'})]; result = evaluate_retrieval_case(case, docs); print(result.case_id, result.recall_at_k, result.reciprocal_rank, result.passed)"
```


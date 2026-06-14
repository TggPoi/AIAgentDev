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

## 本地校验

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -c "from fast_app.evaluation.eval_dataset_loader import load_eval_dataset; dataset = load_eval_dataset('src/fast_app/evaluation/datasets/stage11_rag_eval_cases.json'); print(dataset.name, len(dataset.cases))"
```

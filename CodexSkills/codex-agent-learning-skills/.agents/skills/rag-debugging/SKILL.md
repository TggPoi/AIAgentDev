---
name: rag-debugging
description: Use this skill when the user asks to diagnose poor RAG retrieval quality, irrelevant retrieved documents, missing context, hallucinated answers, bad hybrid retrieval, ES/Milvus/rerank issues, query rewrite problems, or RAG pipeline bugs.
---

## Purpose

Diagnose RAG failures by locating the failing stage in the retrieval-generation chain.

## Core mental model

RAG quality problems usually come from one of these stages:

```text
query rewrite
-> ES keyword recall
-> Milvus vector recall
-> merge/dedupe
-> rerank
-> context formatting
-> final answer prompt
```

Do not blame the LLM first. Inspect retrieval before generation.

## Debugging workflow

### 1. Clarify expected answer and evidence

Ask or infer:
- What should the correct answer contain?
- Which document/chunk should have been retrieved?
- Is the issue missing recall, noisy context, bad ranking, or hallucination?

### 2. Inspect query rewrite

Check:
- Did rewritten queries preserve key entities, IDs, function names, class names, product names, order numbers, and constraints?
- Did rewrite introduce a wrong topic?
- Was original query included together with rewritten queries?

### 3. Inspect ES keyword recall

Check:
- Mapping: `text` vs `keyword`
- Analyzer and `search_analyzer`
- `_analyze` results
- `match` vs `term`
- `bool`, `filter`, `must`, `should`
- BM25 `_score`
- Field boost, especially title vs content

### 4. Inspect Milvus vector recall

Check:
- Embedding model
- Chunk size and overlap
- Metric type, such as L2 / cosine / inner product
- topK
- Whether correct document is semantically close enough

### 5. Inspect merge and dedupe

Check:
- Does each document have stable `metadata.id`?
- Did dedupe remove the correct document accidentally?
- Are ES and Milvus using the same business ID?

### 6. Inspect rerank

Check:
- Did the correct document enter the rerank candidate set?
- Is rerank using the original query, not a drifted rewrite?
- Is topN too small?
- Are documents too long or too short for rerank?

### 7. Inspect context formatting

Check:
- Are document IDs/sources preserved?
- Are chunks separated clearly?
- Is the context too long or noisy?
- Are references/citations required?

### 8. Inspect generation prompt

Check:
- Does the prompt require answering only from context?
- Does it say to admit missing evidence?
- Does it prevent unsupported claims?

## Output format

When diagnosing, return:

1. 最可能失败阶段
2. 证据
3. 修复建议
4. 推荐验证命令或代码
5. 后续优化建议

## Important known issue

If Elasticsearch server is 8.x but `@elastic/elasticsearch` client is 9.x, errors may include:

```text
Accept version must be either version 8 or 7, but found 9.
compatible-with=9
```

Fix by installing an 8.x client for an 8.x ES server.

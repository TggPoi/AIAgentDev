# 真实离线 RAG 评测脚本

脚本路径：

```text
scripts/run_real_offline_rag_eval.py
```

## 使用前提

本地已经启动：

```text
Milvus
ElasticSearch
```

并且已经通过 ingestion 写入同一批知识库数据。

如果写入 Milvus 时使用过：

```powershell
--mock-embeddings
```

评测时也要使用：

```powershell
--embedding-provider mock
```

如果写入 Milvus 时使用真实 Qwen embedding，评测时使用：

```powershell
--embedding-provider qwen
```

## 推荐命令

当前你要测试真实 LLM，可以先运行：

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe scripts\run_real_offline_rag_eval.py `
  --llm-provider qwen `
  --embedding-provider mock `
  --reranker-provider mock `
  --pipeline-provider classic `
  --output-dir reports\evaluation-real
```

这条命令表示：

```text
LLM 使用真实 qwen
Milvus 查询向量使用 mock embedding
rerank 不调用真实 DashScope rerank
pipeline 使用 Classic
报告输出到 reports/evaluation-real
```

如果你的 Milvus 数据是用真实 Qwen embedding 写入的，改成：

```powershell
--embedding-provider qwen
```

如果你也想测试真实 DashScope rerank，改成：

```powershell
--reranker-provider dashscope
```

## 输出结果

脚本会输出：

```text
json_report: reports/evaluation-real/xxx.json
markdown_report: reports/evaluation-real/xxx.md
```

优先打开 Markdown 报告查看：

```text
Summary
Retrieval Results
Generation Results
Failed Generation Details
```

JSON 报告用于后续自动对比和回归。

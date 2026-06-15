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

### 轻量真实 LLM 测试

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

## 带阈值检查的回归命令

当你修改过 RAG 主链路后，可以用阈值命令做最低质量检查：

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

这些阈值只是学习阶段的起点。

如果命令输出：

```text
threshold checks:
  retrieval_mean_recall_at_k: PASS ...
  retrieval_mean_mrr: PASS ...
  generation_pass_rate: FAIL ...
```

说明生成质量低于你设置的最低标准。

如果传入了：

```powershell
--fail-on-threshold
```

任一阈值失败时，脚本会返回退出码 `1`。

这适合后续接入更自动化的回归流程。

## 完整真实 rerank 测试

如果你要观察真实 DashScope rerank 对 sources 排序和最终回答的影响，可以运行：

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe scripts\run_real_offline_rag_eval.py `
  --llm-provider qwen `
  --embedding-provider mock `
  --reranker-provider dashscope `
  --pipeline-provider classic `
  --output-dir reports\evaluation-real-rerank
```

注意：

```text
--reranker-provider dashscope 会额外调用真实 rerank 服务。
```

## 日常修改流程

修改 RAG 主链路前，先运行一次真实离线评测，保存 baseline 报告路径。

修改 RAG 主链路后，使用同一份评测集和同一组参数再次运行脚本。

重点对比：

```text
retrieval mean_recall_at_k
retrieval mean_mrr
generation pass_rate
Failed Generation Details
threshold checks
```

如果阈值失败，不要只看总分，需要打开 Markdown 报告中的失败 case，确认是检索没有命中、rerank 排序变差，还是生成回答没有覆盖关键内容。

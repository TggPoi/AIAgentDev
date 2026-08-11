# 轻量流式 RAG Eval

该模块通过进程内 ASGI 调用真实 `POST /rag/chat/stream/events`，只读复用 Golden V2 与 `EvaluationSnapshot`。它不会修改公开 SSE 协议，也不会把最终完整上下文放入 `sources`。

## 安装隔离 Eval 环境

DeepEval 4.1.3 要求 `click<8.4.0`，而生产依赖固定为 `click==8.4.1`，因此必须使用独立虚拟环境：

```powershell
py -3.12 -m venv .venv-rag-eval
.\.venv-rag-eval\Scripts\python.exe -m pip install -r requirements-eval.txt
.\.venv-rag-eval\Scripts\python.exe -m pip check
```

生成层只读取以下独立 Judge 配置，不复用主生成模型凭据：

```powershell
$env:RAG_EVAL_JUDGE_API_KEY = "your-eval-only-key"
$env:RAG_EVAL_JUDGE_BASE_URL = "https://your-openai-compatible-endpoint/v1"
$env:RAG_EVAL_JUDGE_MODEL_NAME = "qwen-plus"
```

可选配置为 `RAG_EVAL_JUDGE_TEMPERATURE`、`RAG_EVAL_JUDGE_TIMEOUT_SECONDS`、`RAG_EVAL_JUDGE_MAX_RETRIES` 和 `RAG_EVAL_JUDGE_PYTHON`。

DeepEval Worker 强制禁用 dotenv 自动读取、遥测、旧 keyfile、交互提示和磁盘写入。检测到 `CONFIDENT_API_KEY` 时会直接失败，不会上传评测结果。

## 执行

本地未开启认证时，CLI 会按每条 Golden 的 `eval_principal_id` 发送 Demo 用户头。`AUTH_ENABLED=true` 时必须另外配置 `RAG_EVAL_API_KEY` 或 `RAG_EVAL_BEARER_TOKEN`，且 `/auth/me` 返回的用户必须与 case 身份一致。

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\run_streaming_rag_eval.py `
  --pipeline-provider classic `
  --mode all `
  --output-dir reports\rag-eval
```

三种 provider 必须分别运行：

```powershell
.\.venv\Scripts\python.exe scripts\run_streaming_rag_eval.py --pipeline-provider classic --mode all
.\.venv\Scripts\python.exe scripts\run_streaming_rag_eval.py --pipeline-provider langgraph --mode all
.\.venv\Scripts\python.exe scripts\run_streaming_rag_eval.py --pipeline-provider rag_agent --mode all
```

CLI 还支持 `--case-id`、`--max-cases`、`--metrics`、`--include-judge-reason`、`--baseline-report` 和 `--output-dir`。每次运行输出一个稳定 JSON 和一个 Markdown 报告。

## 路由和指标语义

- `simple_rag` 只代表 Router 意图；只有快照记录真实检索阶段，才算进入 `knowledge_retrieval`。
- RAG Golden 被分到 direct answer、Research、Web、NL2SQL、文档操作或澄清时，case 以 `route_mismatch` 失败，不生成检索伪分数。
- 检索指标使用最终 `rerank` 顺序和逻辑 Chunk ID 去重计算 Recall@K、Precision@K、Hit@K/HitRate@K 与 RR/MRR。
- 生成指标使用 DeepEval Faithfulness、Answer Relevancy，以及固定步骤的 Answer Completeness GEval 和 Context Utilization GEval。
- Completeness 的期望事实直接来自 Golden V2 `required_key_facts`，不需要 `reference_answer`。


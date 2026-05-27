测试脚本使用方式：

运行前先启动 FastAPI 服务：

```powershell
$env:PYTHONPATH="src"
python -m uvicorn fast_app.main:app --reload
```

另开一个终端运行测试脚本：

```powershell
python scripts/test_rag_chat_api.py
```

它会依次测试：

- `POST /rag/chat`：打印完整 JSON 响应
- `POST /rag/chat/stream`：实时打印 SSE 流式输出效果

也可以只看流式输出：

```powershell
python scripts/test_rag_chat_api.py --stream-only
```

可自定义参数：

```powershell
python scripts/test_rag_chat_api.py --query "RAG 是什么？" --mode hybrid --top-k 3 --min-score 0.8
```

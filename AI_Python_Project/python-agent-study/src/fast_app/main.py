from fastapi import FastAPI
from fast_app.schemas.chat_schema import ChatRequest, ChatResponse

from fast_app.schemas.rag_schema import (
    RetrievedDocument,
    SearchRequest,
    SearchResponse,
)

# 创建一个 Web 应用对象，后面所有路由都会注册到这个 `app` 上
app = FastAPI()

# 装饰器，把下面这个 `root` 函数注册成 HTTP GET `/` 接口的处理函
@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Hello FastAPI"
    }

@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok"
    }


@app.get("/docs/{doc_id}")
def get_doc(doc_id: str) -> dict[str, str]:
    return {
        "doc_id": doc_id,
        "content": f"mock content for {doc_id}",
    }

@app.get("/search")
def search_docs(
    query: str,
    top_k: int = 5,
) -> dict:
    return {
        "query": query,
        "top_k": top_k,
        "results": [
            f"mock result for {query}"
        ],
    }

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or "new_session"

    return ChatResponse(
        answer=f"Echo: {req.message}",
        session_id=session_id,
    )


@app.post("/rag/search", response_model=SearchResponse)
def rag_search(req: SearchRequest) -> SearchResponse:
    mock_docs = [
        RetrievedDocument(
            id="doc_001",
            content=f"Milvus vector result for: {req.query}",
            score=0.91,
            source="milvus",
        ),
        RetrievedDocument(
            id="doc_002",
            content=f"ElasticSearch keyword result for: {req.query}",
            score=0.88,
            source="elasticsearch",
        ),
        RetrievedDocument(
            id="doc_003",
            content="Low score document",
            score=0.3,
            source="mock",
        ),
    ]

    filtered_docs = [
        doc for doc in mock_docs
        if doc.score >= req.min_score
    ]

    return SearchResponse(
        query=req.query,
        mode=req.mode,
        documents=filtered_docs[: req.top_k],
    )

# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> uvicorn fast_app.main:app --reload
# INFO:     Will watch for changes in these directories: ['D:\\AI_Agent_Project\\AI_Python_Project\\python-agent-study']
# INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
# INFO:     Started reloader process [984] using StatReload
# INFO:     Started server process [12320]
# INFO:     Waiting for application startup.
# INFO:     Application startup complete.


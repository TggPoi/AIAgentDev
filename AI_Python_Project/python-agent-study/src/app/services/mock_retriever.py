from app.schemas.document import RetrievedDoc

# 这个文件负责 mock 检索逻辑。

def retrieve_docs(query: str, top_k: int = 3) -> list[RetrievedDoc]:
    print(f"retrieve query: {query}")

    docs: list[RetrievedDoc] = [
        {
            "id": "doc_001",
            "content": "Milvus is used for vector search.",
            "score": 0.91,
            "source": "milvus",
        },
        {
            "id": "doc_002",
            "content": "ElasticSearch is used for keyword search.",
            "score": 0.88,
            "source": "elasticsearch",
        },
        {
            "id": "doc_003",
            "content": "Hybrid retrieval combines vector and keyword search.",
            "score": 0.95,
            "source": "mock",
        },
    ]

    return docs[:top_k]
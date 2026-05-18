from typing import Literal, TypedDict


RetrievalMode = Literal["vector", "keyword", "hybrid"]


class RetrievedDoc(TypedDict):
    id: str
    content: str
    score: float
    source: str


def retrieve_docs(
    query: str,
    mode: RetrievalMode = "hybrid",
    top_k: int = 5,
) -> list[RetrievedDoc]:
    
    print(f"query={query}, mode={mode}, top_k={top_k}")

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
            "score": 0.87,
            "source": "elasticsearch",
        },
        {
            "id": "doc_003",
            "content": "LangGraph uses StateGraph to build workflows.",
            "score": 0.76,
            "source": "langgraph",
        },
    ]

    #Python 切片的完整格式 [start : stop : step]，这里省略了 start 和 step，默认从列表开头开始，步长为 1，即返回前 top_k 个文档
    #即使 top_k 大于 docs 的长度，也不会报错，而是返回整个 docs 列表
    return docs[:top_k]


def filter_docs_by_score(
    docs: list[RetrievedDoc],
    min_score: float,
) -> list[RetrievedDoc]:
    result: list[RetrievedDoc] = []

    for doc in docs:
        if doc["score"] >= min_score:
            result.append(doc)

    return result


def build_context(docs: list[RetrievedDoc]) -> str:
    contents: list[str] = []

    for doc in docs:
        contents.append(doc["content"])

    return "\n\n".join(contents)


def main() -> None:
    docs = retrieve_docs(
        query="什么是混合检索？",
        mode="hybrid",
        top_k=3,
    )

    filtered_docs = filter_docs_by_score(docs, min_score=0.8)
    context = build_context(filtered_docs)

    print("=== filtered docs ===")
    print(filtered_docs)

    print("=== context ===")
    print(context)


if __name__ == "__main__":
    main()



# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python -m app.type_hint_demo
# query=什么是混合检索？, mode=hybrid, top_k=3
# === filtered docs ===
# [{'id': 'doc_001', 'content': 'Milvus is used for vector search.', 'score': 0.91, 'source': 'milvus'}, {'id': 'doc_002', 'content': 'ElasticSearch is used for keyword search.', 'score': 0.87, 'source': 'elasticsearch'}]
# === context ===
# Milvus is used for vector search.

# ElasticSearch is used for keyword search.
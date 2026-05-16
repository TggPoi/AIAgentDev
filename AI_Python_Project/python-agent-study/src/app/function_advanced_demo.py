def filter_docs_by_score(
    docs: list[dict],
    *,
    min_score: float = 0.8,
) -> list[dict]:
    result: list[dict] = []

    for doc in docs:
        if doc["score"] >= min_score:
            result.append(doc)

    return result


def sort_docs_by_score(
    docs: list[dict],
    *,
    reverse: bool = True,
) -> list[dict]:
    copied_docs = docs.copy()
    copied_docs.sort(key=lambda doc: doc["score"], reverse=reverse)
    return copied_docs


def create_doc_filter(min_score: float):
    def filter_doc(doc: dict) -> bool:
        return doc["score"] >= min_score

    return filter_doc


def log_decorator(func):
    def wrapper(*args, **kwargs):
        print(f"[LOG] start: {func.__name__}")
        result = func(*args, **kwargs)
        print(f"[LOG] end: {func.__name__}")
        return result

    return wrapper


@log_decorator
def retrieve_docs(query: str, *, top_k: int = 5) -> list[dict]:
    print(f"query = {query}, top_k = {top_k}")

    return [
        {"id": "doc_001", "content": "Milvus vector search", "score": 0.82},
        {"id": "doc_002", "content": "ElasticSearch BM25", "score": 0.91},
        {"id": "doc_003", "content": "LangGraph StateGraph", "score": 0.76},
    ]


def main() -> None:
    docs = retrieve_docs("什么是 RAG？", top_k=3)

    print("=== sorted docs ===")
    sorted_docs = sort_docs_by_score(docs)
    print(sorted_docs)

    print("=== filtered docs ===")
    filtered_docs = filter_docs_by_score(sorted_docs, min_score=0.8)
    print(filtered_docs)

    print("=== closure filter ===")
    high_score_filter = create_doc_filter(0.9)
    high_score_docs = [doc for doc in docs if high_score_filter(doc)]
    print(high_score_docs)


if __name__ == "__main__":
    main()



# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python -m app.function_advanced_demo
# [LOG] start: retrieve_docs
# query = 什么是 RAG？, top_k = 3
# [LOG] end: retrieve_docs
# === sorted docs ===
# [{'id': 'doc_002', 'content': 'ElasticSearch BM25', 'score': 0.91}, {'id': 'doc_001', 'content': 'Milvus vector search', 'score': 0.82}, {'id': 'doc_003', 'content': 'LangGraph StateGraph', 'score': 0.76}]
# === filtered docs ===
# [{'id': 'doc_002', 'content': 'ElasticSearch BM25', 'score': 0.91}, {'id': 'doc_001', 'content': 'Milvus vector search', 'score': 0.82}]
# === closure filter ===
# [{'id': 'doc_002', 'content': 'ElasticSearch BM25', 'score': 0.91}]
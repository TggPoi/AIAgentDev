from app.services.context_builder import build_context
from app.services.mock_retriever import retrieve_docs


def main() -> None:
    docs = retrieve_docs("什么是 Hybrid Retrieval？", top_k=3)
    context = build_context(docs)

    print("=== docs ===")
    print(docs)

    print("=== context ===")
    print(context)


if __name__ == "__main__":
    main()


# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python -m app.import_demo_main
# retrieve query: 什么是 Hybrid Retrieval？
# === docs ===
# [{'id': 'doc_001', 'content': 'Milvus is used for vector search.', 'score': 0.91, 'source': 'milvus'}, {'id': 'doc_002', 'content': 'ElasticSearch is used for keyword search.', 'score': 0.88, 'source': 'elasticsearch'}, {'id': 'doc_003', 'content': 'Hybrid retrieval combines vector and keyword search.', 'score': 0.95, 'source': 'mock'}]
# === context ===
# [milvus] Milvus is used for vector search.

# [elasticsearch] ElasticSearch is used for keyword search.

# [mock] Hybrid retrieval combines vector and keyword search.
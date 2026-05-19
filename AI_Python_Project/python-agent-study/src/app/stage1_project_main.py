from app.services.document_loader import DocumentLoadError, load_and_split_text_file

# 阶段一实战：RAG 的前置模块 实现一个简化 Document Loader

def main() -> None:
    file_path = "data/rag_intro.txt"

    try:
        documents = load_and_split_text_file(
            file_path=file_path,
            chunk_size=120,
        )
    except DocumentLoadError as e:
        print(f"加载失败: {e}")
        return

    print("=== documents ===")

    for doc in documents:
        print("id:", doc["id"])
        print("content:", doc["content"])
        print("metadata:", doc["metadata"])
        print("-" * 40)


if __name__ == "__main__":
    main()


# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python -m app.stage1_project_main
# === documents ===
# id: chunk_0
# content: RAG means Retrieval Augmented Generation.
# A RAG system usually contains document loading, text splitting, embedding, vec
# metadata: {'source': 'data/rag_intro.txt', 'chunk_index': 0}
# ----------------------------------------
# id: chunk_1
# content: tor storage, retrieval, context construction, and LLM generation.
# Milvus is often used for vector similarity search.
# Ela
# metadata: {'source': 'data/rag_intro.txt', 'chunk_index': 1}
# ----------------------------------------
# id: chunk_2
# content: sticSearch is often used for keyword search, entity search, and exact matching.
# Hybrid retrieval combines vector search 
# metadata: {'source': 'data/rag_intro.txt', 'chunk_index': 2}
# ----------------------------------------
# id: chunk_3
# content: and keyword search.
# Rerank models can reorder retrieved documents according to the relevance between the query and each 
# metadata: {'source': 'data/rag_intro.txt', 'chunk_index': 3}
# ----------------------------------------
# id: chunk_4
# content: document.
# LangGraph can be used to build stateful AI Agent workflows.
# metadata: {'source': 'data/rag_intro.txt', 'chunk_index': 4}
# ----------------------------------------
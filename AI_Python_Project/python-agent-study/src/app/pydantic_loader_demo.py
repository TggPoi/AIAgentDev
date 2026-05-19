from app.services.document_loader_model import (
    DocumentLoadError,
    load_and_split_text_file_model,
)

# 和 dataclass 版本相比，Pydantic 版本多了：

# 字段校验
# 类型转换
# 错误信息
# model_dump

def main() -> None:
    file_path = "data/rag_intro.txt"

    try:
        documents = load_and_split_text_file_model(
            file_path=file_path,
            chunk_size=120,
        )
    except DocumentLoadError as e:
        print(f"加载失败: {e}")
        return

    for doc in documents:
        print("model:", doc)
        print("dict:", doc.model_dump())
        print("id:", doc.id)
        print("source:", doc.metadata.source)
        print("-" * 40)


if __name__ == "__main__":
    main()


# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python -m app.pydantic_loader_demo
# model: id='chunk_0' content='RAG means Retrieval Augmented Generation.\nA RAG system usually contains document loading, text splitting, embedding, vec' metadata=DocumentMetadata(source='data/rag_intro.txt', chunk_index=0)
# dict: {'id': 'chunk_0', 'content': 'RAG means Retrieval Augmented Generation.\nA RAG system usually contains document loading, text splitting, embedding, vec', 'metadata': {'source': 'data/rag_intro.txt', 'chunk_index': 0}}
# id: chunk_0
# source: data/rag_intro.txt
# ----------------------------------------
# model: id='chunk_1' content='tor storage, retrieval, context construction, and LLM generation.\nMilvus is often used for vector similarity search.\nEla' metadata=DocumentMetadata(source='data/rag_intro.txt', chunk_index=1)
# dict: {'id': 'chunk_1', 'content': 'tor storage, retrieval, context construction, and LLM generation.\nMilvus is often used for vector similarity search.\nEla', 'metadata': {'source': 'data/rag_intro.txt', 'chunk_index': 1}}
# id: chunk_1
# source: data/rag_intro.txt
# ----------------------------------------
# model: id='chunk_2' content='sticSearch is often used for keyword search, entity search, and exact matching.\nHybrid retrieval combines vector search ' metadata=DocumentMetadata(source='data/rag_intro.txt', chunk_index=2)
# dict: {'id': 'chunk_2', 'content': 'sticSearch is often used for keyword search, entity search, and exact matching.\nHybrid retrieval combines vector search ', 'metadata': {'source': 'data/rag_intro.txt', 'chunk_index': 2}}
# id: chunk_2
# source: data/rag_intro.txt
# ----------------------------------------
# model: id='chunk_3' content='and keyword search.\nRerank models can reorder retrieved documents according to the relevance between the query and each ' metadata=DocumentMetadata(source='data/rag_intro.txt', chunk_index=3)
# dict: {'id': 'chunk_3', 'content': 'and keyword search.\nRerank models can reorder retrieved documents according to the relevance between the query and each ', 'metadata': {'source': 'data/rag_intro.txt', 'chunk_index': 3}}
# id: chunk_3
# source: data/rag_intro.txt
# ----------------------------------------
# model: id='chunk_4' content='document.\nLangGraph can be used to build stateful AI Agent workflows.' metadata=DocumentMetadata(source='data/rag_intro.txt', chunk_index=4)
# dict: {'id': 'chunk_4', 'content': 'document.\nLangGraph can be used to build stateful AI Agent workflows.', 'metadata': {'source': 'data/rag_intro.txt', 'chunk_index': 4}}
# id: chunk_4
# source: data/rag_intro.txt
# ----------------------------------------
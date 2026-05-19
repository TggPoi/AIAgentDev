from app.services.rag_loader import RagLoadError, load_document_as_lines


def main() -> None:
    file_path = "data/sample.txt"

    try:
        lines = load_document_as_lines(file_path)
    except RagLoadError as e:
        print(f"加载失败: {e}")
        return

    print("=== loaded lines ===")
    # 生成一个可迭代的对象，迭代时每个元素都是一个 (索引, 元素) 的元组，例如 (0, lines[0])、(1, lines[1])……
    for index, line in enumerate(lines):
        print(f"{index}: {line}")


if __name__ == "__main__":
    main()

# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python -m app.file_io_demo
# === loaded lines ===
# 0: RAG means Retrieval Augmented Generation.
# 1: Milvus is used for vector search.
# 2: ElasticSearch is used for keyword search.
# 3: Rerank is used to reorder retrieved documents.
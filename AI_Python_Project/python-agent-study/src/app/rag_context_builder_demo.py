from fast_app.domain.rag_models import RetrievedDoc
from fast_app.services.rag.rag_context_builder import build_rag_context


def main() -> None:
    docs = [
        RetrievedDoc(
            id="rag_hybrid_001",
            content="混合检索会同时结合向量检索和关键词检索。",
            score=0.03252,
            source="milvus",
        ),
        RetrievedDoc(
            id="rag_vector_001",
            content="向量检索会把文本转换成 embedding 后进行相似度搜索。",
            score=0.01613,
            source="milvus",
        ),
    ]

    context = build_rag_context(
        query="什么是混合检索？",
        docs=docs,
    )

    print(context.context_text)


if __name__ == "__main__":
    main()
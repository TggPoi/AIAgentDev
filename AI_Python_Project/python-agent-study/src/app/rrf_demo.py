from fast_app.domain.rag_models import RetrievedDoc
from fast_app.services.rag.retrieval_fusion import reciprocal_rank_fusion


def main() -> None:
    milvus_docs = [
        RetrievedDoc(
            id="rag_hybrid_001",
            content="混合检索内容",
            score=0.82,
            source="milvus",
        ),
        RetrievedDoc(
            id="rag_vector_001",
            content="向量检索内容",
            score=0.76,
            source="milvus",
        ),
        RetrievedDoc(
            id="milvus_basic_001",
            content="Milvus 内容",
            score=0.71,
            source="milvus",
        ),
    ]

    es_docs = [
        RetrievedDoc(
            id="rag_keyword_001",
            content="关键词检索内容",
            score=4.31,
            source="elasticsearch",
        ),
        RetrievedDoc(
            id="rag_hybrid_001",
            content="混合检索内容",
            score=3.98,
            source="elasticsearch",
        ),
        RetrievedDoc(
            id="es_basic_001",
            content="ES 内容",
            score=3.12,
            source="elasticsearch",
        ),
    ]

    fused_docs = reciprocal_rank_fusion(
        doc_lists=[
            milvus_docs,
            es_docs,
        ],
        top_k=5,
    )

    for doc in fused_docs:
        print("-" * 80)
        print(f"id: {doc.id}")
        print(f"source: {doc.source}")
        print(f"rrf_score: {doc.score}")
        print(f"content: {doc.content}")


if __name__ == "__main__":
    main()
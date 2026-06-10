import asyncio

from fast_app.components.rerankers.dashscope_reranker import DashScopeReranker
from fast_app.core.config import get_settings
from fast_app.domain.rag_models import RetrievedDoc


async def main() -> None:
    settings = get_settings()
    reranker = DashScopeReranker(settings=settings)

    docs = [
        RetrievedDoc(
            id="doc_1",
            content="混合检索会同时结合向量检索和关键词检索。",
            score=0.1,
            source="demo",
        ),
        RetrievedDoc(
            id="doc_2",
            content="FastAPI 是一个 Python Web 框架。",
            score=0.1,
            source="demo",
        ),
        RetrievedDoc(
            id="doc_3",
            content="RRF 会根据每个检索源内部排名进行融合。",
            score=0.1,
            source="demo",
        ),
    ]

    reranked_docs = await reranker.rerank(
        query="什么是混合检索？",
        docs=docs,
        top_k=2,
    )

    for doc in reranked_docs:
        print("-" * 80)
        print(f"id: {doc.id}")
        print(f"score: {doc.score}")
        print(f"content: {doc.content}")


if __name__ == "__main__":
    asyncio.run(main())
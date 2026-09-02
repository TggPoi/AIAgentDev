"""验证在线 Milvus Retriever 使用可让出事件循环的异步客户端。"""

import asyncio

from fast_app.components.embeddings.mock_embedding_client import MockEmbeddingClient
from fast_app.components.retrievers.milvus_vector_retriever import (
    MilvusVectorRetriever,
)
from fast_app.agents.tools.rag_agent_tools import retrieve_knowledge_docs
from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import KnowledgeChunk
from fast_app.domain.rag_models import RetrievedDoc, RetrievalFilters, RetrievalOptions
from fast_app.ingestion.stores.rag_store_writer import upsert_milvus_collection


class ControlledAsyncMilvusClient:
    """通过两个 Event 确定性验证 search 被 await，避免依赖睡眠计时。"""

    def __init__(self) -> None:
        self.search_started = asyncio.Event()
        self.allow_search_to_finish = asyncio.Event()
        self.search_kwargs: dict = {}

    async def search(self, **kwargs):
        self.search_kwargs = kwargs
        self.search_started.set()
        await self.allow_search_to_finish.wait()
        return [
            [
                {
                    "distance": 0.91,
                    "entity": {
                        "id": "chunk-1",
                        "content": "Milvus async retrieval",
                        "title": "Async Milvus",
                        "metadata": {"doc_id": "doc-1"},
                    },
                }
            ]
        ]


class RecordingAsyncMilvusClient:
    """记录公开 Store Interface 发出的异步 Milvus 操作顺序。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def has_collection(self, collection_name: str) -> bool:
        self.calls.append("has_collection")
        return True

    async def load_collection(self, collection_name: str) -> None:
        self.calls.append("load_collection")

    async def upsert(self, *, collection_name: str, data: list[dict]) -> dict:
        self.calls.append("upsert")
        return {"upsert_count": len(data)}

    async def flush(self, collection_name: str) -> None:
        self.calls.append("flush")


class ControlledKeywordRetriever:
    def __init__(self) -> None:
        self.retrieve_started = asyncio.Event()
        self.allow_retrieve_to_finish = asyncio.Event()

    async def retrieve(self, query: str, options: RetrievalOptions) -> list[RetrievedDoc]:
        self.retrieve_started.set()
        await self.allow_retrieve_to_finish.wait()
        return [
            RetrievedDoc(
                id="chunk-1",
                content="Milvus async retrieval",
                score=1.0,
                source="elasticsearch",
                retrieval_sources=["elasticsearch"],
            )
        ]


async def test_retrieve_awaits_async_search_without_blocking_event_loop() -> None:
    settings = Settings(_env_file=None, EMBEDDING_DIM=3)
    client = ControlledAsyncMilvusClient()
    retriever = MilvusVectorRetriever(
        settings=settings,
        embedding_client=MockEmbeddingClient(dim=3),
        client=client,
    )
    options = RetrievalOptions(
        top_k=1,
        candidate_k=2,
        filters=RetrievalFilters(can_read_all=True),
    )

    retrieval_task = asyncio.create_task(retriever.retrieve("async milvus", options))

    # search 只有在 Retriever 真正 await 异步客户端时才会执行到这里。
    await asyncio.wait_for(client.search_started.wait(), timeout=0.5)
    assert not retrieval_task.done(), "Milvus 等待期间 Retriever 应把控制权交还事件循环"

    client.allow_search_to_finish.set()
    docs = await asyncio.wait_for(retrieval_task, timeout=0.5)

    assert [doc.id for doc in docs] == ["chunk-1"]
    assert docs[0].scores.vector_score == 0.91
    assert client.search_kwargs["collection_name"] == settings.milvus_collection_name
    assert client.search_kwargs["limit"] == 2


async def test_upsert_store_awaits_milvus_operations_in_order() -> None:
    settings = Settings(_env_file=None, EMBEDDING_DIM=3)
    client = RecordingAsyncMilvusClient()
    chunk = KnowledgeChunk(
        id="chunk-1",
        content="async store write",
        source="docs/async.md",
        title="Async Store",
        metadata={
            "doc_id": "doc-1",
            "source_path": "docs/async.md",
            "document_type": "markdown",
            "chunk_index": 0,
        },
    )

    result = await upsert_milvus_collection(
        client=client,
        settings=settings,
        chunks=[chunk],
        vectors=[[0.1, 0.2, 0.3]],
    )

    assert result == {"upsert_count": 1}
    assert client.calls == [
        "has_collection",
        "load_collection",
        "upsert",
        "flush",
        "load_collection",
    ]


async def test_hybrid_retrieval_starts_vector_and_keyword_sources_concurrently() -> None:
    settings = Settings(_env_file=None, EMBEDDING_DIM=3)
    milvus_client = ControlledAsyncMilvusClient()
    keyword_retriever = ControlledKeywordRetriever()
    vector_retriever = MilvusVectorRetriever(
        settings=settings,
        embedding_client=MockEmbeddingClient(dim=3),
        client=milvus_client,
    )

    hybrid_task = asyncio.create_task(
        retrieve_knowledge_docs(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            query="hybrid async retrieval",
            mode="hybrid",
            top_k=1,
            candidate_k=2,
            min_score=0.0,
            filters=RetrievalFilters(can_read_all=True),
        )
    )

    await asyncio.wait_for(
        asyncio.gather(
            milvus_client.search_started.wait(),
            keyword_retriever.retrieve_started.wait(),
        ),
        timeout=0.5,
    )
    assert not hybrid_task.done(), "两个召回源都应在任一来源结束前启动"

    milvus_client.allow_search_to_finish.set()
    keyword_retriever.allow_retrieve_to_finish.set()
    docs = await asyncio.wait_for(hybrid_task, timeout=0.5)
    assert [doc.id for doc in docs] == ["chunk-1"]
    assert set(docs[0].retrieval_sources) == {"milvus", "elasticsearch"}


async def main() -> None:
    await test_retrieve_awaits_async_search_without_blocking_event_loop()
    await test_upsert_store_awaits_milvus_operations_in_order()
    await test_hybrid_retrieval_starts_vector_and_keyword_sources_concurrently()
    print("milvus_async_client=passed")


if __name__ == "__main__":
    asyncio.run(main())

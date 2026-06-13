from dataclasses import dataclass

from elasticsearch import AsyncElasticsearch
from pymilvus import MilvusClient

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import KnowledgeChunk
from fast_app.ingestion.chunk_builders import ChunkBuildOptions, MarkdownChunkBuilder
from fast_app.ingestion.rag_store_writer import (
    recreate_es_index,
    recreate_milvus_collection,
)
from fast_app.ingestion.document_loaders import (
    BaseDocumentLoader,
    CompositeDocumentLoader,
    MarkdownDocumentLoader,
    TextDocumentLoader,
)

# 读取 Markdown
# 构造 chunks
# 批量 embedding
# 验证向量数量和维度
# 写入 ES
# 写入 Milvus
# 返回 ingestion 结果


@dataclass(frozen=True)
class MarkdownIngestionResult:
    document_count: int
    chunk_count: int
    es_success_count: int
    milvus_insert_result: dict


class MarkdownIngestionService:
    def __init__(
        self,
        settings: Settings,
        embedding_client: BaseEmbeddingClient,
        elasticsearch_client: AsyncElasticsearch,
        milvus_client: MilvusClient,
        document_loader: BaseDocumentLoader | None = None,
        chunk_builder: MarkdownChunkBuilder | None = None,
    ):
        self.settings = settings
        self.embedding_client = embedding_client
        self.elasticsearch_client = elasticsearch_client
        self.milvus_client = milvus_client
        self.document_loader = document_loader or CompositeDocumentLoader(
            loaders=[
                MarkdownDocumentLoader(),
                TextDocumentLoader(),
            ]
        )
        self.chunk_builder = chunk_builder or MarkdownChunkBuilder()

    async def ingest(self) -> MarkdownIngestionResult:
        documents = self.document_loader.load(self.settings.knowledge_base_dir)
        chunks = self.chunk_builder.build(
            documents=documents,
            options=ChunkBuildOptions(
                source=self.settings.ingestion_source_name,
                max_chars=self.settings.markdown_chunk_max_chars,
                overlap_chars=self.settings.markdown_chunk_overlap_chars,
                max_tokens=self.settings.markdown_chunk_max_tokens,
                min_chars=self.settings.markdown_chunk_min_chars,
            ),
        )

        vectors = await self.embedding_client.embed_documents(
            [chunk.content for chunk in chunks]
        )

        self._validate_vectors(chunks, vectors)

        es_success_count = await recreate_es_index(
            client=self.elasticsearch_client,
            settings=self.settings,
            chunks=chunks,
        )

        milvus_insert_result = recreate_milvus_collection(
            client=self.milvus_client,
            settings=self.settings,
            chunks=chunks,
            vectors=vectors,
        )

        return MarkdownIngestionResult(
            document_count=len(documents),
            chunk_count=len(chunks),
            es_success_count=es_success_count,
            milvus_insert_result=milvus_insert_result,
        )

    def _validate_vectors(
        self,
        chunks: list[KnowledgeChunk],
        vectors: list[list[float]],
    ) -> None:
        if len(chunks) != len(vectors):
            raise RuntimeError(
                f"chunk 和 embedding 数量不一致: chunks={len(chunks)}, vectors={len(vectors)}"
            )

        for vector in vectors:
            if len(vector) != self.settings.embedding_dim:
                raise RuntimeError(
                    "embedding 维度不匹配: "
                    f"actual={len(vector)}, settings={self.settings.embedding_dim}"
                )

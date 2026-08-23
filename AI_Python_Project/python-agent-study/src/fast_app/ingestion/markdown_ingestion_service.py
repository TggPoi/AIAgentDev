from dataclasses import dataclass
from contextlib import asynccontextmanager
import hashlib

from elasticsearch import AsyncElasticsearch
from pymilvus import MilvusClient

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import KnowledgeChunk
from fast_app.ingestion.processing.chunk_builders import ChunkBuildOptions, MarkdownChunkBuilder
from fast_app.ingestion.processing.markdown_hierarchy import (
    MarkdownHierarchyBuilder,
    MarkdownHierarchyOptions,
)
from fast_app.ingestion.stores.rag_store_writer import write_rag_stores
from fast_app.ingestion.processing.document_loaders import (
    BaseDocumentLoader,
    build_default_document_loader,
)
from fast_app.ingestion.processing.metadata_models import apply_local_corpus_ownership
from fast_app.ingestion.stores.store_mutation_lock import StoreMutationLock


@dataclass(frozen=True)
class MarkdownIngestionResult:
    # 这里返回的是“本次导入的汇总结果”，不是 ES / Milvus 的完整底层响应。
    # 上层 CLI 或 API 只需要知道处理了多少文档、多少 chunk、写入是否成功。
    document_count: int
    chunk_count: int
    parent_count: int
    es_success_count: int
    milvus_insert_result: dict


class MarkdownIngestionService:
    # 这个 service 是 ingestion 的主编排层：
    # 1. 读取知识库目录中的文档
    # 2. 把文档切成 KnowledgeChunk
    # 3. 为每个 chunk 生成 embedding
    # 4. 校验 chunk 和 embedding 是否能一一对应
    # 5. 交给 write_rag_stores 统一写入 ES 和 Milvus
    #
    # 它本身不直接解析 Markdown 细节，也不直接拼 ES / Milvus 写入数据。
    # 这些细节分别交给 document_loader、chunk_builder、write_rag_stores 处理。
    def __init__(
        self,
        settings: Settings,
        embedding_client: BaseEmbeddingClient,
        elasticsearch_client: AsyncElasticsearch,
        milvus_client: MilvusClient,
        document_loader: BaseDocumentLoader | None = None,
        chunk_builder: MarkdownChunkBuilder | None = None,
        hierarchy_builder: MarkdownHierarchyBuilder | None = None,
        store_mutation_lock: StoreMutationLock | None = None,
    ):
        # settings 是本次导入使用的配置来源，例如知识库目录、chunk 大小、
        # ES index 名称、Milvus collection 名称、写入模式等。
        self.settings = settings

        # embedding_client 只负责把文本转换成向量。
        # service 不关心它背后是真实模型、DashScope，还是测试用的 mock embedding。
        self.embedding_client = embedding_client

        # ES / Milvus client 由外层创建后注入进来。
        # 这样 service 不需要关心连接如何建立，也方便 CLI、测试、FastAPI 复用同一套流程。
        self.elasticsearch_client = elasticsearch_client
        self.milvus_client = milvus_client

        # document_loader 支持外部传入，测试可注入假 Loader；默认工厂统一装配文本和 Office Loader。
        self.document_loader = document_loader or build_default_document_loader()

        # chunk_builder 负责把领域文档切成 KnowledgeChunk，并生成稳定的 chunk_id / metadata。
        # 主流程只消费它的结果，不在这里写具体切分规则。
        self.chunk_builder = chunk_builder or MarkdownChunkBuilder()
        self.hierarchy_builder = hierarchy_builder or MarkdownHierarchyBuilder()
        self.store_mutation_lock = store_mutation_lock

    async def ingest(self) -> MarkdownIngestionResult:
        # 第一步：从配置中的知识库目录读取原始文档。
        # 返回值是 KnowledgeDocument 列表，里面包含文档内容和基础元数据。
        documents = self.document_loader.load(self.settings.knowledge_base_dir)
        for document in documents:
            document.metadata = apply_local_corpus_ownership(
                document.metadata,
                local_corpus_id=self.settings.local_corpus_id,
                source_revision=hashlib.sha256(
                    document.content.encode("utf-8")
                ).hexdigest(),
            )

        # 第二步：把文档拆成可检索、可向量化的 chunk。
        # ChunkBuildOptions 把配置层的参数集中传给 chunk_builder，
        # 避免 chunk_builder 直接依赖 Settings。
        markdown_documents = [
            document for document in documents if document.document_type == "markdown"
        ]
        legacy_documents = [
            document for document in documents if document.document_type != "markdown"
        ]
        hierarchy = self.hierarchy_builder.build(
            documents=markdown_documents,
            options=MarkdownHierarchyOptions(
                source=self.settings.ingestion_source_name,
                parent_target_tokens=self.settings.markdown_parent_target_tokens,
                parent_max_tokens=self.settings.markdown_parent_max_tokens,
                parent_max_chars=self.settings.markdown_parent_max_chars,
                child_target_tokens=self.settings.markdown_child_target_tokens,
                child_max_tokens=self.settings.markdown_child_max_tokens,
                child_min_tokens=self.settings.markdown_child_min_tokens,
                child_overlap_tokens=self.settings.markdown_child_overlap_tokens,
            ),
        )
        legacy_chunks = self.chunk_builder.build(
            documents=legacy_documents,
            options=ChunkBuildOptions(
                source=self.settings.ingestion_source_name,
                max_chars=self.settings.markdown_chunk_max_chars,
                overlap_chars=self.settings.markdown_chunk_overlap_chars,
                max_tokens=self.settings.markdown_chunk_max_tokens,
                min_chars=self.settings.markdown_chunk_min_chars,
            ),
        )
        chunks = [*hierarchy.children, *legacy_chunks]

        # 第三步：按 chunks 的顺序生成 embedding。
        # 这里必须只传 chunk.content，因为 embedding 模型只需要正文文本。
        # vectors 的顺序后面会和 chunks 的顺序一一配对，不能打乱。
        vectors = await self.embedding_client.embed_documents(
            [chunk.search_text or chunk.content for chunk in chunks]
        )

        # 第四步：写入存储前先做数量和维度校验。
        # 如果这里不提前拦截，后面可能出现“chunk 写入成功但向量不匹配”的脏数据。
        self._validate_vectors(chunks, vectors)

        # 第五步：把 chunks 和 vectors 交给统一写入函数。
        # write_rag_stores 内部会根据 settings.ingestion_write_mode 决定是 recreate、
        # upsert，还是 replace_docs，并分别完成 ES 与 Milvus 的写入。
        async with self._store_mutation_guard():
            store_write_result = await write_rag_stores(
                elasticsearch_client=self.elasticsearch_client,
                milvus_client=self.milvus_client,
                settings=self.settings,
                chunks=chunks,
                vectors=vectors,
                parents=hierarchy.parents,
            )

        # 第六步：把底层写入结果整理成上层更容易理解的导入结果。
        return MarkdownIngestionResult(
            document_count=len(documents),
            chunk_count=len(chunks),
            parent_count=len(hierarchy.parents),
            es_success_count=store_write_result.es.success_count,
            milvus_insert_result=store_write_result.milvus.detail,
        )

    @asynccontextmanager
    async def _store_mutation_guard(self):
        if self.store_mutation_lock is None:
            yield
            return
        async with self.store_mutation_lock.hold():
            yield

    def _validate_vectors(
        self,
        chunks: list[KnowledgeChunk],
        vectors: list[list[float]],
    ) -> None:
        # 每个 chunk 必须对应一个 vector。
        # 如果数量不一致，后续写入时就无法判断哪个向量属于哪个 chunk。
        if len(chunks) != len(vectors):
            raise RuntimeError(
                f"chunk 和 embedding 数量不一致: chunks={len(chunks)}, vectors={len(vectors)}"
            )

        for vector in vectors:
            # Milvus collection 的向量字段有固定维度。
            # 如果模型实际返回的维度和 settings.embedding_dim 不一致，
            # 插入 Milvus 会失败，即使 ES 文本写入可能已经成功。
            if len(vector) != self.settings.embedding_dim:
                raise RuntimeError(
                    "embedding 维度不匹配: "
                    f"actual={len(vector)}, settings={self.settings.embedding_dim}"
                )

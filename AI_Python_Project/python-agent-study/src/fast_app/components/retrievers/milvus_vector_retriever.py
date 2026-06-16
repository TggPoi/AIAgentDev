from dataclasses import dataclass
from time import perf_counter

from pymilvus import MilvusClient

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.latency import log_slow_operation
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.services.exceptions import ExternalServiceError
from fast_app.domain.rag_models import RetrievalFilters, RetrievalOptions, RetrievedDoc, ScoreBreakdown
from fast_app.ingestion.rag_store_schema import (
    MILVUS_CHUNK_INDEX_FIELD,
    MILVUS_DOC_ID_FIELD,
    MILVUS_DOCUMENT_TYPE_FIELD,
    MILVUS_METADATA_FIELD,
    MILVUS_SOURCE_PATH_FIELD,
    MILVUS_TITLE_FIELD,
    build_milvus_output_fields,
)


logger = get_logger(__name__)

# 检索结果转换同时返回 docs 和 skipped_hit_count。
@dataclass
class MilvusConvertResult:
    docs: list[RetrievedDoc]
    # 因为缺少 id / content 被跳过的 hit 数量
    skipped_hit_count: int


def build_milvus_uri(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def escape_milvus_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_milvus_filter_expr(filters: RetrievalFilters) -> str | None:
    expressions: list[str] = []

    if filters.source_path:
        source_path = escape_milvus_string(filters.source_path)
        expressions.append(f'{MILVUS_SOURCE_PATH_FIELD} == "{source_path}"')

    if filters.section_path:
        section_path = escape_milvus_string(filters.section_path[-1])
        expressions.append(
            f'array_contains({MILVUS_METADATA_FIELD}["section_path"], "{section_path}")'
        )

    if not expressions:
        return None

    return " and ".join(expressions)

# 统计 Milvus 原始 hit 数量
def count_milvus_hits(results: list) -> int:
    if not results:
        return 0

    return len(results[0])


def build_top_doc_ids(docs: list[RetrievedDoc], limit: int = 5) -> list[str]:
    return [doc.id for doc in docs[:limit]]


class MilvusVectorRetriever(BaseRetriever):
    def __init__(
        self,
        settings: Settings,
        embedding_client: BaseEmbeddingClient,
        client: MilvusClient | None = None,
    ):
        self.settings = settings
        self.embedding_client = embedding_client

        if client is not None:
            self.client = client
        else:
            uri = build_milvus_uri(
                host=settings.milvus_host,
                port=settings.milvus_port,
            )
            self.client = MilvusClient(uri=uri)


    async def retrieve(
        self,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedDoc]:
        total_start_time = perf_counter()
        filter_expr: str | None = None
        output_fields: list[str] = []

        try:
            embedding_start_time = perf_counter()

            query_vector = await self.embedding_client.embed_query(query)
            embedding_latency_ms = (perf_counter() - embedding_start_time) * 1000

            logger.info(
                "milvus_search %s",
                format_log_fields(
                    event="milvus.embedding.finish",
                    query_length=len(query),
                    embedding_dim=self.settings.embedding_dim,
                    actual_embedding_dim=len(query_vector),
                    embedding_latency_ms=round(embedding_latency_ms, 2),
                ),
            )

            if len(query_vector) != self.settings.embedding_dim:
                latency_ms = (perf_counter() - total_start_time) * 1000
                logger.error(
                    "milvus_search %s",
                    format_log_fields(
                        event="milvus.search.failed",
                        reason="embedding_dim_mismatch",
                        collection_name=self.settings.milvus_collection_name,
                        anns_field=self.settings.milvus_vector_field,
                        limit=options.candidate_k,
                        embedding_dim=self.settings.embedding_dim,
                        actual_embedding_dim=len(query_vector),
                        latency_ms=round(latency_ms, 2),
                    ),
                )
                raise ExternalServiceError(
                    "query embedding 维度不匹配: "
                    f"actual={len(query_vector)}, settings={self.settings.embedding_dim}"
                )

            # 构建过滤条件 milvus filter表达式
            filter_expr = build_milvus_filter_expr(options.filters)
            output_fields = options.output_fields or build_milvus_output_fields(self.settings)

            logger.info(
                "milvus_search %s",
                format_log_fields(
                    event="milvus.search.start",
                    collection_name=self.settings.milvus_collection_name,
                    anns_field=self.settings.milvus_vector_field,
                    metric_type="COSINE",
                    limit=options.candidate_k,
                    filter_expr=filter_expr,
                    output_fields=output_fields,
                    output_field_count=len(output_fields),
                ),
            )

            results = self.client.search(
                collection_name=self.settings.milvus_collection_name,
                data=[query_vector],
                anns_field=self.settings.milvus_vector_field,
                limit=options.candidate_k,
                filter=filter_expr,
                output_fields=output_fields,
                search_params={
                    "metric_type": "COSINE",
                    "params": {},
                },
            )

            convert_result = self._convert_results_to_docs(results)
            docs = convert_result.docs
            latency_ms = (perf_counter() - total_start_time) * 1000

            logger.info(
                "milvus_search %s",
                format_log_fields(
                    event="milvus.search.finish",
                    collection_name=self.settings.milvus_collection_name,
                    anns_field=self.settings.milvus_vector_field,
                    metric_type="COSINE",
                    limit=options.candidate_k,
                    filter_expr=filter_expr,
                    output_field_count=len(output_fields),
                    hit_count=count_milvus_hits(results),
                    doc_count=len(docs),
                    skipped_hit_count=convert_result.skipped_hit_count,
                    latency_ms=round(latency_ms, 2),
                    top_doc_ids=build_top_doc_ids(docs),
                ),
            )
            log_slow_operation(
                logger=logger,
                event="milvus.search.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_retrieval_threshold_ms,
                slow_component="milvus",
                collection_name=self.settings.milvus_collection_name,
                limit=options.candidate_k,
                filter_expr=filter_expr,
                output_field_count=len(output_fields),
                hit_count=count_milvus_hits(results),
                doc_count=len(docs),
                skipped_hit_count=convert_result.skipped_hit_count,
            )

            return docs

        except ExternalServiceError:
            raise

        except Exception as exc:
            latency_ms = (perf_counter() - total_start_time) * 1000
            logger.exception(
                "milvus_search %s",
                format_log_fields(
                    event="milvus.search.failed",
                    collection_name=self.settings.milvus_collection_name,
                    anns_field=self.settings.milvus_vector_field,
                    limit=options.candidate_k,
                    filter_expr=filter_expr,
                    output_field_count=len(output_fields),
                    error_type=type(exc).__name__,
                    latency_ms=round(latency_ms, 2),
                ),
            )
            log_slow_operation(
                logger=logger,
                event="milvus.search.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_retrieval_threshold_ms,
                slow_component="milvus",
                collection_name=self.settings.milvus_collection_name,
                limit=options.candidate_k,
                filter_expr=filter_expr,
                output_field_count=len(output_fields),
                status="failed",
                error_type=type(exc).__name__,
            )
            raise ExternalServiceError(f"Milvus 向量检索失败: {exc}") from exc

    def _convert_results_to_docs(self, results: list) -> MilvusConvertResult:
        if not results:
            return MilvusConvertResult(docs=[], skipped_hit_count=0)

        docs: list[RetrievedDoc] = []
        skipped_hit_count = 0

        for hit in results[0]:
            entity = hit.get("entity", {})

            doc_id = entity.get(self.settings.milvus_id_field)
            content = entity.get(self.settings.milvus_content_field)

            if not doc_id or not content:
                skipped_hit_count += 1
                logger.warning(
                    "milvus_hit %s",
                    format_log_fields(
                        event="milvus.hit.skipped",
                        reason="missing_id_or_content",
                        has_id=bool(doc_id),
                        has_content=bool(content),
                    ),
                )
                continue

            distance = float(hit.get("distance", 0.0))
            title = entity.get(MILVUS_TITLE_FIELD)
            metadata = entity.get(MILVUS_METADATA_FIELD, {})

            if not isinstance(metadata, dict):
                metadata = {}

            metadata.setdefault(MILVUS_DOC_ID_FIELD, entity.get(MILVUS_DOC_ID_FIELD))
            metadata.setdefault(
                MILVUS_SOURCE_PATH_FIELD,
                entity.get(MILVUS_SOURCE_PATH_FIELD),
            )
            metadata.setdefault(
                MILVUS_DOCUMENT_TYPE_FIELD,
                entity.get(MILVUS_DOCUMENT_TYPE_FIELD),
            )
            metadata.setdefault(
                MILVUS_CHUNK_INDEX_FIELD,
                entity.get(MILVUS_CHUNK_INDEX_FIELD),
            )

            docs.append(
                RetrievedDoc(
                    id=str(doc_id),
                    content=str(content),
                    score=distance,
                    source="milvus",
                    title=str(title) if title else None,
                    metadata=metadata,
                    retrieval_sources=["milvus"],
                    scores=ScoreBreakdown(vector_score=distance),
                )
            )

        return MilvusConvertResult(
            docs=docs,
            skipped_hit_count=skipped_hit_count,
        )

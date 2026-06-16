from dataclasses import dataclass
from time import perf_counter
from typing import Any

from elasticsearch import AsyncElasticsearch

from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.latency import log_slow_operation
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.rag_models import RetrievalFilters, RetrievalOptions, RetrievedDoc, ScoreBreakdown
from fast_app.ingestion.rag_store_schema import (
    ES_CONTENT_FIELD,
    ES_ID_FIELD,
    ES_IK_INDEX_ANALYZER,
    ES_IK_SEARCH_ANALYZER,
    ES_METADATA_FIELD,
    ES_METADATA_SECTION_PATH_FIELD,
    ES_METADATA_SOURCE_PATH_FIELD,
    ES_TITLE_FIELD,
)
from fast_app.services.exceptions import ExternalServiceError


logger = get_logger(__name__)


@dataclass
class ElasticsearchConvertResult:
    docs: list[RetrievedDoc]
    skipped_hit_count: int


def build_es_filters(filters: RetrievalFilters) -> list[dict[str, Any]]:
    es_filters: list[dict[str, Any]] = []

    if filters.source_path:
        es_filters.append(
            {"term": {ES_METADATA_SOURCE_PATH_FIELD: filters.source_path}}
        )

    if filters.section_path:
        es_filters.append(
            {"terms": {ES_METADATA_SECTION_PATH_FIELD: filters.section_path}}
        )

    return es_filters


def get_es_hits(response: dict[str, Any]) -> list[dict[str, Any]]:
    hits = response.get("hits", {}).get("hits", [])
    return hits if isinstance(hits, list) else []


def get_es_total(response: dict[str, Any]) -> tuple[int | None, str | None]:
    total = response.get("hits", {}).get("total")

    if not isinstance(total, dict):
        return None, None

    value = total.get("value")
    relation = total.get("relation")
    return (
        int(value) if isinstance(value, int) else None,
        str(relation) if relation else None,
    )


def build_top_doc_ids(docs: list[RetrievedDoc], limit: int = 5) -> list[str]:
    return [doc.id for doc in docs[:limit]]


# 构建查询条件
def build_es_query(query: str, filters: RetrievalFilters) -> dict[str, Any]:
    filter_clauses = build_es_filters(filters)

    if not filter_clauses:
        return {
            "match": {
                ES_CONTENT_FIELD: {
                    "query": query,
                }
            }
        }

    return {
        "bool": {
            "must": [
                {
                    "match": {
                        ES_CONTENT_FIELD: {
                            "query": query,
                        }
                    }
                }
            ],
            "filter": filter_clauses,
        }
    }


class ElasticsearchKeywordRetriever(BaseRetriever):
    def __init__(
        self,
        settings: Settings,
        client: AsyncElasticsearch | None = None,
    ):
        self.settings = settings
        self.client = client or AsyncElasticsearch(
            hosts=[settings.elasticsearch_url],
        )

    async def retrieve(
        self,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedDoc]:
        query_body = build_es_query(query, options.filters)
        filter_clauses = build_es_filters(options.filters)
        start_time = perf_counter()

        try:
            logger.info(
                "elasticsearch_search %s",
                format_log_fields(
                    event="elasticsearch.search.start",
                    index_name=self.settings.elasticsearch_index_name,
                    query_field=ES_CONTENT_FIELD,
                    index_analyzer=ES_IK_INDEX_ANALYZER,
                    search_analyzer=ES_IK_SEARCH_ANALYZER,
                    size=options.candidate_k,
                    request_timeout=self.settings.elasticsearch_request_timeout,
                    filter_count=len(filter_clauses),
                    has_filter=bool(filter_clauses),
                    query_body=query_body,
                ),
            )

            response = await self.client.search(
                index=self.settings.elasticsearch_index_name,
                query=query_body,
                size=options.candidate_k,
                # 增加请求级 timeout
                request_timeout=self.settings.elasticsearch_request_timeout,
            )

            convert_result = self._convert_hits_to_docs(response)
            docs = convert_result.docs
            total_value, total_relation = get_es_total(response)
            latency_ms = (perf_counter() - start_time) * 1000

            logger.info(
                "elasticsearch_search %s",
                format_log_fields(
                    event="elasticsearch.search.finish",
                    index_name=self.settings.elasticsearch_index_name,
                    query_field=ES_CONTENT_FIELD,
                    size=options.candidate_k,
                    request_timeout=self.settings.elasticsearch_request_timeout,
                    filter_count=len(filter_clauses),
                    has_filter=bool(filter_clauses),
                    hit_count=len(get_es_hits(response)),
                    total_value=total_value,
                    total_relation=total_relation,
                    doc_count=len(docs),
                    skipped_hit_count=convert_result.skipped_hit_count,
                    latency_ms=round(latency_ms, 2),
                    top_doc_ids=build_top_doc_ids(docs),
                ),
            )
            log_slow_operation(
                logger=logger,
                event="elasticsearch.search.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_retrieval_threshold_ms,
                slow_component="elasticsearch",
                index_name=self.settings.elasticsearch_index_name,
                size=options.candidate_k,
                filter_count=len(filter_clauses),
                has_filter=bool(filter_clauses),
                hit_count=len(get_es_hits(response)),
                total_value=total_value,
                total_relation=total_relation,
                doc_count=len(docs),
                skipped_hit_count=convert_result.skipped_hit_count,
            )

            return docs

        except Exception as exc:
            latency_ms = (perf_counter() - start_time) * 1000
            logger.exception(
                "elasticsearch_search %s",
                format_log_fields(
                    event="elasticsearch.search.failed",
                    index_name=self.settings.elasticsearch_index_name,
                    query_field=ES_CONTENT_FIELD,
                    size=options.candidate_k,
                    request_timeout=self.settings.elasticsearch_request_timeout,
                    filter_count=len(filter_clauses),
                    has_filter=bool(filter_clauses),
                    error_type=type(exc).__name__,
                    latency_ms=round(latency_ms, 2),
                ),
            )
            log_slow_operation(
                logger=logger,
                event="elasticsearch.search.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_retrieval_threshold_ms,
                slow_component="elasticsearch",
                index_name=self.settings.elasticsearch_index_name,
                size=options.candidate_k,
                filter_count=len(filter_clauses),
                has_filter=bool(filter_clauses),
                status="failed",
                error_type=type(exc).__name__,
            )
            raise ExternalServiceError(f"ElasticSearch 关键词检索失败: {exc}") from exc

    async def close(self) -> None:
        await self.client.close()

    def _convert_hits_to_docs(self, response: dict[str, Any]) -> ElasticsearchConvertResult:
        hits = get_es_hits(response)
        docs: list[RetrievedDoc] = []
        skipped_hit_count = 0

        for hit in hits:
            source = hit.get("_source", {})

            doc_id = source.get(ES_ID_FIELD)
            content = source.get(ES_CONTENT_FIELD)

            if not doc_id or not content:
                skipped_hit_count += 1
                logger.warning(
                    "elasticsearch_hit %s",
                    format_log_fields(
                        event="elasticsearch.hit.skipped",
                        reason="missing_id_or_content",
                        has_id=bool(doc_id),
                        has_content=bool(content),
                    ),
                )
                continue

            keyword_score = float(hit.get("_score", 0.0))
            title = source.get(ES_TITLE_FIELD)
            metadata = source.get(ES_METADATA_FIELD, {})

            docs.append(
                RetrievedDoc(
                    id=str(doc_id),
                    content=str(content),
                    score=keyword_score,
                    source="elasticsearch",
                    title=str(title) if title else None,
                    metadata=metadata if isinstance(metadata, dict) else {},
                    retrieval_sources=["elasticsearch"],
                    scores=ScoreBreakdown(keyword_score=keyword_score),
                )
            )

        return ElasticsearchConvertResult(
            docs=docs,
            skipped_hit_count=skipped_hit_count,
        )

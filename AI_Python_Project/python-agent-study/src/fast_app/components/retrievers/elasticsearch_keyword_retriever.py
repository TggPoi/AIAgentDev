from typing import Any

from elasticsearch import AsyncElasticsearch

from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.logging import get_logger
from fast_app.domain.rag_models import RetrievalFilters, RetrievalOptions, RetrievedDoc, ScoreBreakdown
from fast_app.ingestion.rag_store_schema import (
    ES_CONTENT_FIELD,
    ES_ID_FIELD,
    ES_METADATA_FIELD,
    ES_METADATA_SECTION_PATH_FIELD,
    ES_METADATA_SOURCE_PATH_FIELD,
    ES_TITLE_FIELD,
)
from fast_app.services.exceptions import ExternalServiceError


logger = get_logger(__name__)


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
        try:
            logger.info("开始 ElasticSearch 关键词检索: query=%s", query)

            response = await self.client.search(
                index=self.settings.elasticsearch_index_name,
                query=build_es_query(query, options.filters),
                size=options.candidate_k,
                # 增加请求级 timeout
                request_timeout=self.settings.elasticsearch_request_timeout,
            )

            docs = self._convert_hits_to_docs(response)

            logger.info("ElasticSearch 关键词检索完成: docs_count=%s", len(docs))

            return docs

        except Exception as exc:
            logger.exception("ElasticSearch 关键词检索失败")
            raise ExternalServiceError(f"ElasticSearch 关键词检索失败: {exc}") from exc

    async def close(self) -> None:
        await self.client.close()

    def _convert_hits_to_docs(self, response: dict[str, Any]) -> list[RetrievedDoc]:
        hits = response.get("hits", {}).get("hits", [])

        docs: list[RetrievedDoc] = []

        for hit in hits:
            source = hit.get("_source", {})

            doc_id = source.get(ES_ID_FIELD)
            content = source.get(ES_CONTENT_FIELD)

            if not doc_id or not content:
                logger.warning("ElasticSearch hit 缺少 id 或 content: hit=%s", hit)
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

        return docs

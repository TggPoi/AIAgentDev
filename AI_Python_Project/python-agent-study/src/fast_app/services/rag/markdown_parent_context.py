from __future__ import annotations

import hashlib
from time import perf_counter
from typing import Any, Mapping

from elasticsearch import AsyncElasticsearch

from fast_app.components.retrievers.elasticsearch_keyword_retriever import (
    build_es_filters,
    get_es_hits,
)
from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.rag_models import RetrievalFilters, RetrievedDoc
from fast_app.ingestion.processing.markdown_hierarchy import (
    MARKDOWN_CHILD_RECORD_TYPE,
    MARKDOWN_PARENT_RECORD_TYPE,
)
from fast_app.ingestion.stores.rag_store_schema import (
    ES_CONTENT_FIELD,
    ES_ID_FIELD,
    ES_METADATA_DOCUMENT_TYPE_FIELD,
    ES_METADATA_FIELD,
    ES_RECORD_TYPE_FIELD,
    ES_SOURCE_FIELD,
    ES_TITLE_FIELD,
)
from fast_app.services.rag.rag_context_builder import (
    count_structured_context_tokens,
)


logger = get_logger(__name__)
MAX_EVIDENCE_CHILDREN = 12


class MarkdownParentContextExpander:
    """把 rerank 后的 Markdown 子块安全扩展成有界父块。"""

    def __init__(
        self,
        settings: Settings,
        client: AsyncElasticsearch | None,
    ) -> None:
        self._settings = settings
        self._client = client

    async def expand(
        self,
        docs: list[RetrievedDoc],
        filters: RetrievalFilters,
    ) -> list[RetrievedDoc]:
        if not self._settings.rag_parent_expansion_enabled or not docs:
            return docs

        evidence_docs = docs[:MAX_EVIDENCE_CHILDREN]
        groups = self._group_markdown_children(evidence_docs)
        if not groups:
            return evidence_docs

        parent_ids = list(groups)
        start_time = perf_counter()
        try:
            parents = await self._load_parents(parent_ids, filters)
        except Exception as exc:
            latency_ms = (perf_counter() - start_time) * 1000
            logger.warning(
                "markdown_parent_expansion %s",
                format_log_fields(
                    event="rag.parent_expansion.degraded",
                    child_hit_count=len(evidence_docs),
                    unique_parent_count=len(parent_ids),
                    parent_lookup_latency_ms=round(latency_ms, 2),
                    expanded_count=0,
                    fallback_count=len(groups),
                    parent_expansion_degraded=True,
                    error_type=type(exc).__name__,
                ),
            )
            return self._replace_with_fallbacks(
                evidence_docs,
                groups,
                {},
                latency_ms=latency_ms,
            )

        latency_ms = (perf_counter() - start_time) * 1000
        expanded_docs = self._replace_with_fallbacks(
            evidence_docs,
            groups,
            parents,
            latency_ms=latency_ms,
        )
        expanded_count = sum(
            doc.metadata.get("chunk_level") == "parent" for doc in expanded_docs
        )
        fallback_count = sum(
            doc.metadata.get("parent_expansion_degraded") is True
            for doc in expanded_docs
        )
        logger.info(
            "markdown_parent_expansion %s",
            format_log_fields(
                event="rag.parent_expansion.finish",
                child_hit_count=len(evidence_docs),
                unique_parent_count=len(parent_ids),
                parent_lookup_latency_ms=round(latency_ms, 2),
                expanded_count=expanded_count,
                fallback_count=fallback_count,
                context_token_count=sum(
                    int(doc.metadata.get("token_count") or 0)
                    for doc in expanded_docs
                ),
                chunk_strategy_version=self._strategy_versions(expanded_docs),
                parent_expansion_degraded=bool(fallback_count),
            ),
        )
        return expanded_docs

    @staticmethod
    def _group_markdown_children(
        docs: list[RetrievedDoc],
    ) -> dict[str, list[RetrievedDoc]]:
        groups: dict[str, list[RetrievedDoc]] = {}
        for doc in docs:
            metadata = doc.metadata
            if (
                metadata.get("document_type") == "markdown"
                and metadata.get("record_type") == MARKDOWN_CHILD_RECORD_TYPE
                and metadata.get("parent_id")
            ):
                groups.setdefault(str(metadata["parent_id"]), []).append(doc)
        return groups

    async def _load_parents(
        self,
        parent_ids: list[str],
        filters: RetrievalFilters,
    ) -> dict[str, Mapping[str, Any]]:
        if self._client is None:
            raise RuntimeError("Elasticsearch client 未初始化")

        query_filters = [
            {"ids": {"values": parent_ids}},
            {"term": {ES_RECORD_TYPE_FIELD: MARKDOWN_PARENT_RECORD_TYPE}},
            {"term": {ES_METADATA_DOCUMENT_TYPE_FIELD: "markdown"}},
            *build_es_filters(filters),
        ]
        response = await self._client.search(
            index=self._settings.elasticsearch_index_name,
            query={"bool": {"filter": query_filters}},
            size=len(parent_ids),
            request_timeout=self._settings.elasticsearch_request_timeout,
        )
        parents: dict[str, Mapping[str, Any]] = {}
        for hit in get_es_hits(response):
            source = hit.get("_source")
            if not isinstance(source, Mapping):
                continue
            parent_id = str(source.get(ES_ID_FIELD) or hit.get("_id") or "")
            metadata = source.get(ES_METADATA_FIELD)
            if parent_id and isinstance(metadata, Mapping):
                parents[parent_id] = source
        return parents

    def _replace_with_fallbacks(
        self,
        docs: list[RetrievedDoc],
        groups: dict[str, list[RetrievedDoc]],
        parents: dict[str, Mapping[str, Any]],
        *,
        latency_ms: float,
    ) -> list[RetrievedDoc]:
        results: list[RetrievedDoc] = []
        handled_parents: set[str] = set()
        parent_count = 0

        for doc in docs:
            parent_id = str(doc.metadata.get("parent_id") or "")
            children = groups.get(parent_id)
            if not children:
                results.append(doc)
                continue
            if parent_id in handled_parents:
                continue
            handled_parents.add(parent_id)

            best_child = max(children, key=lambda item: item.score)
            parent_source = parents.get(parent_id)
            parent_doc = self._build_parent_doc(
                parent_id=parent_id,
                source=parent_source,
                children=children,
                best_child=best_child,
            )
            can_add_parent = (
                parent_doc is not None
                and parent_count < self._settings.rag_parent_context_max_parents
                and count_structured_context_tokens([*results, parent_doc])
                <= self._settings.rag_parent_context_max_tokens
            )
            if can_add_parent:
                parent_doc.metadata["parent_lookup_latency_ms"] = round(
                    latency_ms, 2
                )
                results.append(parent_doc)
                parent_count += 1
                continue

            fallback = self._build_fallback_doc(best_child, children)
            fallback.metadata["parent_lookup_latency_ms"] = round(latency_ms, 2)
            results.append(fallback)
        return results

    def _build_parent_doc(
        self,
        *,
        parent_id: str,
        source: Mapping[str, Any] | None,
        children: list[RetrievedDoc],
        best_child: RetrievedDoc,
    ) -> RetrievedDoc | None:
        if source is None:
            return None
        metadata = source.get(ES_METADATA_FIELD)
        content = source.get(ES_CONTENT_FIELD)
        if not isinstance(metadata, Mapping) or not isinstance(content, str):
            return None
        strategy_version = metadata.get("chunk_strategy_version")
        token_count = metadata.get("token_count")
        if (
            metadata.get("parent_id") != parent_id
            or metadata.get("doc_id") != best_child.metadata.get("doc_id")
            or not strategy_version
            or strategy_version != best_child.metadata.get("chunk_strategy_version")
            or not isinstance(token_count, int)
            or token_count <= 0
            or token_count > self._settings.markdown_parent_max_tokens
            or metadata.get("char_count") != len(content)
            or metadata.get("content_hash")
            != hashlib.sha256(content.encode("utf-8")).hexdigest()
            or any(
                metadata.get(key) != best_child.metadata.get(key)
                for key in (
                    "visibility",
                    "allowed_departments",
                    "allowed_users",
                    "permission_source",
                )
            )
        ):
            return None

        parent_metadata = dict(metadata)
        parent_metadata.update(
            {
                "chunk_level": "parent",
                "matched_child_ids": [child.id for child in children],
                "matched_logical_child_ids": [
                    str(child.metadata.get("logical_record_id") or child.id)
                    for child in children
                ],
                "parent_expansion_degraded": False,
            }
        )
        return RetrievedDoc(
            id=parent_id,
            content=content,
            score=best_child.score,
            source=str(source.get(ES_SOURCE_FIELD) or best_child.source),
            title=(
                str(source[ES_TITLE_FIELD])
                if source.get(ES_TITLE_FIELD) is not None
                else best_child.title
            ),
            metadata=parent_metadata,
            retrieval_sources=MarkdownParentContextExpander._merge_retrieval_sources(
                children
            ),
            scores=best_child.scores,
        )

    def _build_fallback_doc(
        self,
        best_child: RetrievedDoc,
        children: list[RetrievedDoc],
    ) -> RetrievedDoc:
        fallback_metadata = dict(best_child.metadata)
        fallback_metadata.update(
            {
                "chunk_level": "child",
                "matched_child_ids": [child.id for child in children],
                "matched_logical_child_ids": [
                    str(child.metadata.get("logical_record_id") or child.id)
                    for child in children
                ],
                "parent_expansion_degraded": True,
            }
        )
        return RetrievedDoc(
            id=best_child.id,
            content=best_child.content,
            score=best_child.score,
            source=best_child.source,
            title=best_child.title,
            metadata=fallback_metadata,
            retrieval_sources=self._merge_retrieval_sources(children),
            scores=best_child.scores,
        )

    @staticmethod
    def _merge_retrieval_sources(docs: list[RetrievedDoc]) -> list[str]:
        return sorted(
            {
                source
                for doc in docs
                for source in (doc.retrieval_sources or [doc.source])
            }
        )

    @staticmethod
    def _strategy_versions(docs: list[RetrievedDoc]) -> list[str]:
        return sorted(
            {
                str(version)
                for doc in docs
                if (version := doc.metadata.get("chunk_strategy_version"))
            }
        )

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
    ES_METADATA_ALLOWED_DEPARTMENTS_FIELD,
    ES_METADATA_ALLOWED_USERS_FIELD,
    ES_METADATA_FIELD,
    ES_METADATA_SECTION_PATH_FIELD,
    ES_METADATA_SOURCE_PATH_FIELD,
    ES_METADATA_VISIBILITY_FIELD,
    ES_TITLE_FIELD,
)
from fast_app.services.exceptions import ExternalServiceError


logger = get_logger(__name__)


@dataclass
class ElasticsearchConvertResult:
    """ES 命中结果转换后的内部结果。

    docs 是成功转换成 RetrievedDoc 的结果；skipped_hit_count 用于记录因为缺少
    id 或 content 被跳过的 ES hit，方便日志里判断索引数据是否存在脏数据。
    """

    docs: list[RetrievedDoc]
    skipped_hit_count: int


def build_es_filters(filters: RetrievalFilters) -> list[dict[str, Any]]:
    """把内部 RetrievalFilters 转换成 Elasticsearch filter 子句。

    source_path / section_path 是用户侧的业务过滤条件；权限过滤条件来自服务端
    CurrentUserContext 生成的 RetrievalFilters。这里统一拼成 ES bool.filter
    可以直接使用的列表，保证关键词召回阶段就完成权限下推。
    """

    es_filters: list[dict[str, Any]] = []

    if filters.source_path:
        # term 用于精确匹配 keyword 字段，适合 source_path 这种不需要分词的 metadata。
        es_filters.append(
            {"term": {ES_METADATA_SOURCE_PATH_FIELD: filters.source_path}}
        )

    if filters.section_path:
        # terms 表示“命中任意一个章节路径即可”，适合用户传入多个 section_path 的场景。
        es_filters.append(
            {"terms": {ES_METADATA_SECTION_PATH_FIELD: filters.section_path}}
        )

    permission_filter = build_es_permission_filter(filters)
    if permission_filter is not None:
        es_filters.append(permission_filter)

    return es_filters


def build_es_permission_filter(filters: RetrievalFilters) -> dict[str, Any] | None:
    """构造 ES 文档权限过滤条件。

    管理员或具备 knowledge:read:all 的用户会被转换成 can_read_all=True，此时不加
    权限 filter。普通用户只能命中 public 文档、所属部门文档，或显式授权给自己的
    文档。这个 filter 会进入 ES 查询阶段，避免先召回无权限文档再在 Python 中删除。
    """

    if filters.can_read_all:
        return None

    should_clauses: list[dict[str, Any]] = []

    if filters.allow_public:
        # public 文档对当前允许访问公开知识库的用户可见。
        should_clauses.append({"term": {ES_METADATA_VISIBILITY_FIELD: "public"}})

    if filters.department_codes:
        # allowed_departments 是 keyword 数组字段；terms 表示用户任一部门命中即可访问。
        should_clauses.append(
            {
                "terms": {
                    ES_METADATA_ALLOWED_DEPARTMENTS_FIELD: filters.department_codes
                }
            }
        )

    if filters.user_id:
        # allowed_users 支持把单篇文档显式共享给某个用户。
        should_clauses.append({"term": {ES_METADATA_ALLOWED_USERS_FIELD: filters.user_id}})

    if not should_clauses:
        # 没有任何可访问范围时，构造一个必定无法命中的条件，避免放开检索边界。
        return {"term": {ES_METADATA_VISIBILITY_FIELD: "__deny_all__"}}

    return {
        "bool": {
            "should": should_clauses,
            "minimum_should_match": 1,
        }
    }


def get_es_hits(response: dict[str, Any]) -> list[dict[str, Any]]:
    """从 ES 原始响应中安全取出 hits 列表。

    ES 客户端返回的是嵌套 dict。这里做一次类型保护，避免异常响应或测试 mock
    返回非列表时影响后续转换逻辑。
    """

    hits = response.get("hits", {}).get("hits", [])
    return hits if isinstance(hits, list) else []


def get_es_total(response: dict[str, Any]) -> tuple[int | None, str | None]:
    """从 ES 响应中读取 total.value 和 total.relation。

    total 用于日志和 trace，不参与排序或业务判断。因此无法解析时返回 None，
    不因为观测字段缺失影响主检索链路。
    """

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
    """提取前几个 doc id 写入日志。

    日志只记录少量 id，既能辅助排查召回结果，又避免把完整文档内容写进日志。
    """

    return [doc.id for doc in docs[:limit]]


def build_es_query(query: str, filters: RetrievalFilters) -> dict[str, Any]:
    """构造 Elasticsearch match 查询。

    没有 filter 时返回普通 match query；有业务过滤或权限过滤时，使用 bool.must
    承载正文 match，使用 bool.filter 承载 metadata 和权限条件。filter 不参与相关性
    评分，更适合 source_path、section_path、permission 这类硬约束。
    """

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
        """初始化关键词检索器。

        FastAPI lifespan 中通常会传入复用的 AsyncElasticsearch client；测试或临时
        使用时也可以不传 client，让 retriever 根据 settings 自行创建。
        """

        self.settings = settings
        self.client = client or AsyncElasticsearch(
            hosts=[settings.elasticsearch_url],
        )

    async def retrieve(
        self,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedDoc]:
        """执行 Elasticsearch 关键词检索并返回统一 RetrievedDoc。

        这里负责三件事：构造 ES 查询、调用 ES search、把原始 hits 转成领域模型。
        日志中记录 query body、filter 数量、耗时和跳过 hit 数，便于排查中文关键词
        召回、权限 filter 和索引数据质量问题。
        """

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
                # 请求级 timeout 防止 ES 慢查询拖住整条 RAG 链路。
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
        """关闭 ES 异步客户端连接。"""

        await self.client.close()

    def _convert_hits_to_docs(self, response: dict[str, Any]) -> ElasticsearchConvertResult:
        """把 ES hits 转换成 RAG 主链路使用的 RetrievedDoc。

        ES 的 _score 被保留为 keyword_score，后续 hybrid / RRF / rerank 可以继续使用
        多阶段分数。缺少 doc_id 或 content 的 hit 会被跳过并记录告警，避免脏数据
        进入 LLM context。
        """

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

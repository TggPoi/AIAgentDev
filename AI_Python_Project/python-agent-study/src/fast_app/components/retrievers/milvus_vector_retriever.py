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
from fast_app.ingestion.stores.rag_store_schema import (
    MILVUS_CHUNK_INDEX_FIELD,
    MILVUS_DOC_ID_FIELD,
    MILVUS_DOCUMENT_TYPE_FIELD,
    MILVUS_METADATA_FIELD,
    MILVUS_SOURCE_PATH_FIELD,
    MILVUS_TITLE_FIELD,
    build_milvus_output_fields,
)


logger = get_logger(__name__)

@dataclass
class MilvusConvertResult:
    """Milvus 原始结果转换后的内部结果。

    docs 是成功转换为 RetrievedDoc 的结果；skipped_hit_count 记录因为缺少 id
    或 content 被跳过的 hit 数，便于从日志判断 collection 中是否存在脏数据。
    """

    docs: list[RetrievedDoc]
    skipped_hit_count: int


def build_milvus_uri(host: str, port: int) -> str:
    """根据 Milvus host / port 拼出 pymilvus 客户端使用的 HTTP URI。"""

    return f"http://{host}:{port}"


def escape_milvus_string(value: str) -> str:
    """转义 Milvus filter 表达式中的字符串值。

    Milvus filter 是字符串表达式，用户输入或 metadata 值中如果包含反斜杠、双引号，
    需要先转义，避免生成非法表达式或改变过滤条件语义。
    """

    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_milvus_filter_expr(filters: RetrievalFilters) -> str | None:
    """把内部 RetrievalFilters 转成 Milvus filter 表达式。

    source_path / section_path 是业务过滤条件；permission_expr 是服务端权限条件。
    这些条件用 and 组合，表示“既要满足用户查询范围，也要满足访问权限”。
    """

    expressions: list[str] = []

    if filters.source_path:
        # source_path 是 Milvus 顶层 scalar 字段，可以直接使用等值过滤。
        source_path = escape_milvus_string(filters.source_path)
        expressions.append(f'{MILVUS_SOURCE_PATH_FIELD} == "{source_path}"')

    if filters.section_path:
        # section_path 存在 metadata JSON 数组中。这里只取最后一级章节名，和当前 ES
        # 侧的 section_path 过滤语义保持一致。
        section_path = escape_milvus_string(filters.section_path[-1])
        expressions.append(
            f'array_contains({MILVUS_METADATA_FIELD}["section_path"], "{section_path}")'
        )

    permission_expr = build_milvus_permission_filter_expr(filters)
    if permission_expr is not None:
        expressions.append(permission_expr)

    if not expressions:
        return None

    return " and ".join(expressions)


def build_milvus_permission_filter_expr(filters: RetrievalFilters) -> str | None:
    """构造 Milvus 文档权限过滤表达式。

    can_read_all=True 表示管理员或 knowledge:read:all 用户，不附加权限 filter。
    普通用户只能召回 public 文档、所属部门文档，或 allowed_users 中显式包含自己的
    文档。这个表达式会下推到 Milvus search 阶段，而不是召回后再做 Python 后过滤。
    """

    if filters.can_read_all:
        return None

    permission_expressions: list[str] = []

    if filters.allow_public:
        # public 文档是普通认证用户默认可见的跨部门文档。
        permission_expressions.append(
            f'{MILVUS_METADATA_FIELD}["visibility"] == "public"'
        )

    for department_code in filters.department_codes:
        # 一个用户可以属于多个部门；任一部门命中 allowed_departments 即可访问。
        escaped_department_code = escape_milvus_string(department_code)
        permission_expressions.append(
            f'array_contains({MILVUS_METADATA_FIELD}["allowed_departments"], "{escaped_department_code}")'
        )

    if filters.user_id:
        # allowed_users 用于单篇文档显式授权给某个用户的场景。
        user_id = escape_milvus_string(filters.user_id)
        permission_expressions.append(
            f'array_contains({MILVUS_METADATA_FIELD}["allowed_users"], "{user_id}")'
        )

    if not permission_expressions:
        # 没有任何可访问范围时，返回一个必定不命中的表达式，避免误放开权限。
        return f'{MILVUS_METADATA_FIELD}["visibility"] == "__deny_all__"'

    return "(" + " or ".join(permission_expressions) + ")"


def count_milvus_hits(results: list) -> int:
    """统计 Milvus 原始 hit 数量。

    当前检索一次只传入一个 query vector，因此 pymilvus 返回结构通常是
    results[0] 对应该 query 的命中列表。
    """

    if not results:
        return 0

    return len(results[0])


def build_top_doc_ids(docs: list[RetrievedDoc], limit: int = 5) -> list[str]:
    """提取前几个 doc id 写入日志，避免日志输出完整文档内容。"""

    return [doc.id for doc in docs[:limit]]


class MilvusVectorRetriever(BaseRetriever):
    def __init__(
        self,
        settings: Settings,
        embedding_client: BaseEmbeddingClient,
        client: MilvusClient | None = None,
    ):
        """初始化 Milvus 向量检索器。

        embedding_client 负责把 query 转成向量；MilvusClient 负责向量召回。
        FastAPI lifespan 中通常会注入复用 client，测试或脚本场景也可以让 retriever
        根据 settings 自行创建 client。
        """

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
        """执行 Milvus 向量检索并返回统一 RetrievedDoc。

        主流程是：生成 query embedding、校验向量维度、构造 Milvus filter、
        执行 search、把原始 hits 转换成 RAG 主链路使用的 RetrievedDoc。日志会记录
        embedding 耗时、filter_expr、output_fields、命中数和跳过数，方便排查召回与权限问题。
        """

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

            # 过滤表达式同时包含用户业务过滤和服务端权限过滤。
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
                # filter 会在 Milvus 召回阶段生效，避免无权限文档进入候选集。
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
            # 业务上已经包装过的外部服务错误直接抛出，避免重复包一层导致定位困难。
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
        """把 Milvus 原始 hits 转换成 RAG 主链路使用的 RetrievedDoc。

        Milvus distance 在 COSINE 检索下作为 vector_score 保留，后续 RRF / rerank
        可以继续使用多阶段分数。metadata 会从 JSON 字段读取，并用顶层字段补齐
        doc_id、source_path、document_type、chunk_index 等追溯信息。
        """

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

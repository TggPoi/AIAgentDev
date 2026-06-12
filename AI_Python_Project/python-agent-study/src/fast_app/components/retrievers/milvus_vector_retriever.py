from pymilvus import MilvusClient

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.logging import get_logger
from fast_app.services.exceptions import ExternalServiceError
from fast_app.domain.rag_models import RetrievalFilters, RetrievalOptions, RetrievedDoc, ScoreBreakdown


logger = get_logger(__name__)


def build_milvus_uri(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def build_milvus_output_fields(settings: Settings) -> list[str]:
    return [
        settings.milvus_id_field,
        settings.milvus_content_field,
        "source",
        "title",
        "metadata",
    ]


def build_milvus_filter_expr(filters: RetrievalFilters) -> str | None:
    expressions: list[str] = []

    if filters.source_path:
        expressions.append(f'metadata["source_path"] == "{filters.source_path}"')

    if filters.section_path:
        section_path = filters.section_path[-1]
        expressions.append(f'array_contains(metadata["section_path"], "{section_path}")')

    if not expressions:
        return None

    return " and ".join(expressions)


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
        try:
            logger.info("开始 Milvus 向量检索: query=%s", query)

            query_vector = await self.embedding_client.embed_query(query)

            if len(query_vector) != self.settings.embedding_dim:
                raise ExternalServiceError(
                    "query embedding 维度不匹配: "
                    f"actual={len(query_vector)}, settings={self.settings.embedding_dim}"
                )

            # 构建过滤条件 milvus filter表达式
            filter_expr = build_milvus_filter_expr(options.filters)
            output_fields = options.output_fields or build_milvus_output_fields(self.settings)

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

            docs = self._convert_results_to_docs(results)

            logger.info("Milvus 向量检索完成: docs_count=%s", len(docs))

            return docs

        except ExternalServiceError:
            raise

        except Exception as exc:
            logger.exception("Milvus 向量检索失败")
            raise ExternalServiceError(f"Milvus 向量检索失败: {exc}") from exc

    def _convert_results_to_docs(self, results: list) -> list[RetrievedDoc]:
        if not results:
            return []

        docs: list[RetrievedDoc] = []

        for hit in results[0]:
            entity = hit.get("entity", {})

            doc_id = entity.get(self.settings.milvus_id_field)
            content = entity.get(self.settings.milvus_content_field)

            if not doc_id or not content:
                logger.warning("Milvus hit 缺少 id 或 content: hit=%s", hit)
                continue

            distance = float(hit.get("distance", 0.0))
            title = entity.get("title")
            # 目前测试用的milvus里面没有metadata，需要重新创建Collection 补充测试数据
            metadata = entity.get("metadata", {})

            docs.append(
                RetrievedDoc(
                    id=str(doc_id),
                    content=str(content),
                    score=distance,
                    source="milvus",
                    title=str(title) if title else None,
                    metadata=metadata if isinstance(metadata, dict) else {},
                    retrieval_sources=["milvus"],
                    scores=ScoreBreakdown(vector_score=distance),
                )
            )

        return docs

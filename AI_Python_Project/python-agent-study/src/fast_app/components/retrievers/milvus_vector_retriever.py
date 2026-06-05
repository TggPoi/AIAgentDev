from pymilvus import MilvusClient

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.logging import get_logger
from fast_app.domain.rag_models import RetrievedDoc
from fast_app.services.exceptions import ExternalServiceError


logger = get_logger(__name__)


def build_milvus_uri(host: str, port: int) -> str:
    return f"http://{host}:{port}"


class MilvusVectorRetriever(BaseRetriever):
    def __init__(
        self,
        settings: Settings,
        embedding_client: BaseEmbeddingClient,
    ):
        self.settings = settings
        self.embedding_client = embedding_client

        uri = build_milvus_uri(
            host=settings.milvus_host,
            port=settings.milvus_port,
        )

        self.client = MilvusClient(uri=uri)

    async def retrieve(self, query: str) -> list[RetrievedDoc]:
        try:
            logger.info("开始 Milvus 向量检索: query=%s", query)

            query_vector = await self.embedding_client.embed_query(query)

            if len(query_vector) != self.settings.embedding_dim:
                raise ExternalServiceError(
                    "query embedding 维度不匹配: "
                    f"actual={len(query_vector)}, settings={self.settings.embedding_dim}"
                )

            results = self.client.search(
                collection_name=self.settings.milvus_collection_name,
                data=[query_vector],
                anns_field=self.settings.milvus_vector_field,
                limit=self.settings.rag_default_top_k,
                output_fields=[
                    self.settings.milvus_id_field,
                    self.settings.milvus_content_field,
                    "source",
                    "title",
                ],
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

            docs.append(
                RetrievedDoc(
                    id=str(doc_id),
                    content=str(content),
                    score=float(hit.get("distance", 0.0)),
                    source="milvus",
                )
            )

        return docs
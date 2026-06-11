from dataclasses import replace
from typing import Any

import httpx

from fast_app.components.rerankers.base import BaseReranker
from fast_app.core.config import Settings
from fast_app.core.logging import get_logger
from fast_app.domain.rag_models import RetrievedDoc
from fast_app.services.exceptions import ExternalServiceError


logger = get_logger(__name__)


DASHSCOPE_RERANK_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"


class DashScopeReranker(BaseReranker):
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY 为空，无法调用 DashScope Rerank 模型")

        self.settings = settings

    async def rerank(
        self,
        query: str,
        docs: list[RetrievedDoc],
        top_k: int,
    ) -> list[RetrievedDoc]:
        if not docs:
            return []

        documents = [doc.content for doc in docs]

        payload = {
            "model": self.settings.rerank_model_name,
            "input": {
                "query": query,
                "documents": documents,
            },
            "parameters": {
                "return_documents": False,
                "top_n": min(top_k, len(docs)),
            },
        }

        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    DASHSCOPE_RERANK_URL,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()

            data = response.json()

            return self._convert_response_to_docs(
                data=data,
                docs=docs,
                top_k=top_k,
            )

        except httpx.HTTPStatusError as exc:
            logger.exception("DashScope Rerank HTTP 状态错误")
            raise ExternalServiceError(
                f"DashScope Rerank 调用失败: status={exc.response.status_code}, body={exc.response.text}"
            ) from exc

        except Exception as exc:
            logger.exception("DashScope Rerank 调用失败")
            raise ExternalServiceError(f"DashScope Rerank 调用失败: {exc}") from exc

    def _convert_response_to_docs(
        self,
        data: dict[str, Any],
        docs: list[RetrievedDoc],
        top_k: int,
    ) -> list[RetrievedDoc]:
        results = data.get("output", {}).get("results", [])

        logger.info("Rerank result =%s", data)

        reranked_docs: list[RetrievedDoc] = []

        for item in results[:top_k]:
            # 这里的 `index` 表示：这个结果对应你请求时传入的 documents 数组里的第几个文档。
            index = item.get("index")
            relevance_score = item.get("relevance_score")

            if index is None or relevance_score is None:
                logger.warning("Rerank result 缺少 index 或 relevance_score: item=%s", item)
                continue
            # 将原始文档顺序的index 和原始文档对象匹配
            original_doc = docs[int(index)]

            rerank_score = float(relevance_score)

            reranked_docs.append(
                replace(
                    original_doc,
                    score=rerank_score,
                    scores=replace(
                        original_doc.scores,
                        rerank_score=rerank_score,
                    ),
                )
            )

        return reranked_docs
    

# rerank响应日志
# 2026-06-11 18:22:53,265 | INFO | httpx | HTTP Request: POST https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank "HTTP/1.1 200 OK"
# 2026-06-11 18:22:53,265 | INFO | fast_app.components.rerankers.dashscope_reranker | Rerank result ={'output': {'results': [{'index': 0, 'relevance_score': 0.985890866059624}, {'index': 2, 'relevance_score': 0.4768717704752586}, {'index': 4, 'relevance_score': 0.4755436492386353}, {'index': 3, 'relevance_score': 0.45392317343721855}, {'index': 1, 'relevance_score': 0.40762123741699546}]}, 'usage': {'total_tokens': 366}, 'request_id': '04501a19-3628-963a-a16f-b3689fd5fc78'}
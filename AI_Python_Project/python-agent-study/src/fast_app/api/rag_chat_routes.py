from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from fast_app.dependencies.rag_dependencies import get_rag_pipeline
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse
from fast_app.services.exceptions import ExternalServiceError, NoSearchResultError
from fast_app.services.rag_pipeline_service import RagPipeline

from fast_app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/rag", tags=["rag-chat"])

# pipeline: RagPipeline = Depends(get_rag_pipeline)

# 这个接口函数需要一个 RagPipeline。
# 这个 RagPipeline 不由我在函数内部手动创建。
# 请 FastAPI 在调用接口函数之前，先执行 get_rag_pipeline()。
# 然后把返回值传给 pipeline 参数
@router.post("/chat", response_model=RagChatResponse)
async def rag_chat_endpoint(
    req: RagChatRequest,
    pipeline: RagPipeline = Depends(get_rag_pipeline),
) -> RagChatResponse:
    return await pipeline.run(req)


async def rag_chat_sse_event_generator(
    req: RagChatRequest,
    pipeline: RagPipeline,
) -> AsyncGenerator[str, None]:
    try:
        async for token in pipeline.stream(req):
            yield f"data: {token}\n\n"

        yield "event: done\ndata: [DONE]\n\n"

    except NoSearchResultError as e:
        yield (
            "event: error\n"
            f"data: NO_SEARCH_RESULT: {str(e)}\n\n"
        )

    except ExternalServiceError as e:
        yield (
            "event: error\n"
            f"data: EXTERNAL_SERVICE_ERROR: {str(e)}\n\n"
        )

    except Exception:
        logger.exception("RAG SSE 流式输出发生未知异常")
        yield (
            "event: error\n"
            "data: INTERNAL_SERVER_ERROR: 服务器内部错误\n\n"
        )


@router.post("/chat/stream")
async def rag_chat_stream_endpoint(
    req: RagChatRequest,
    pipeline: RagPipeline = Depends(get_rag_pipeline),
) -> StreamingResponse:
    return StreamingResponse(
        rag_chat_sse_event_generator(req, pipeline),
        media_type="text/event-stream",
    )
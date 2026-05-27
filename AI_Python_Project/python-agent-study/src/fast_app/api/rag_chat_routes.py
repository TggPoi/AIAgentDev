from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse
from fast_app.services.exceptions import ExternalServiceError, NoSearchResultError
from fast_app.services.rag_pipeline_service import run_rag, run_rag_stream

# 声明 HTTP 路由
# 接收 RagChatRequest
# 调用 service
# 把业务异常转换成 HTTPException 或 SSE error event
# 把 token 包装成 SSE 格式
# 返回 StreamingResponse

router = APIRouter(prefix="/rag", tags=["rag-chat"])


@router.post("/chat", response_model=RagChatResponse)
async def rag_chat_endpoint(req: RagChatRequest) -> RagChatResponse:
    try:
        return await run_rag(req)

    except NoSearchResultError as e:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NO_SEARCH_RESULT",
                "message": str(e),
            },
        ) from e

    except ExternalServiceError as e:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "EXTERNAL_SERVICE_ERROR",
                "message": str(e),
            },
        ) from e


async def rag_chat_sse_event_generator(
    req: RagChatRequest,
) -> AsyncGenerator[str, None]:
    # service 层产生业务 token
    # api 层负责 SSE 协议格式
    try:
        async for token in run_rag_stream(req):
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


@router.post("/chat/stream")
async def rag_chat_stream_endpoint(req: RagChatRequest) -> StreamingResponse:
    return StreamingResponse(
        rag_chat_sse_event_generator(req),
        media_type="text/event-stream",
    )
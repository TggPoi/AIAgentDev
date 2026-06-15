from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from fast_app.dependencies.rag_dependencies import get_rag_pipeline
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse
from fast_app.services.exceptions import ExternalServiceError, NoSearchResultError
from fast_app.services.rag_pipeline_service import RagPipeline

from fast_app.core.logging import get_logger
from fast_app.core.request_context import get_request_id, get_trace_id

import json
from fastapi.encoders import jsonable_encoder

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
    response = await pipeline.run(req)
    response.request_id = get_request_id()
    response.trace_id = get_trace_id()
    return response


#token处理，放在API层面，保持pipeline的纯粹性
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


# 流式事件格式化工具函数，事件包括：sources（检索结果）和token（生成的回答token）
# sources 里包含 RagSource 这种 Pydantic model, json.dumps() 不能直接序列化 Pydantic model，所以需要先用 jsonable_encoder 转成 dict，再序列化成字符串。
def format_sse_event(event: str, data: object) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"
    )

# 结构化 SSE 生成器
async def rag_chat_structured_sse_event_generator(
    req: RagChatRequest,
    pipeline: RagPipeline,
) -> AsyncGenerator[str, None]:
    try:
        async for stream_event in pipeline.stream_events(req):
            yield format_sse_event(
                event=stream_event.event,
                data=stream_event.data,
            )

        yield format_sse_event(
            event="done",
            data={
                "status": "done",
            },
        )

    except NoSearchResultError as e:
        yield format_sse_event(
            event="error",
            data={
                "code": "NO_SEARCH_RESULT",
                "message": str(e),
            },
        )

    except ExternalServiceError as e:
        yield format_sse_event(
            event="error",
            data={
                "code": "EXTERNAL_SERVICE_ERROR",
                "message": str(e),
            },
        )

    except Exception:
        logger.exception("RAG 结构化 SSE 流式输出发生未知异常")
        yield format_sse_event(
            event="error",
            data={
                "code": "INTERNAL_SERVER_ERROR",
                "message": "服务器内部错误",
            },
        )


@router.post("/chat/stream/events")
async def rag_chat_stream_events_endpoint(
    req: RagChatRequest,
    pipeline: RagPipeline = Depends(get_rag_pipeline),
) -> StreamingResponse:
    return StreamingResponse(
        rag_chat_structured_sse_event_generator(req, pipeline),
        media_type="text/event-stream",
    )

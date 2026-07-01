from collections.abc import AsyncGenerator
from time import perf_counter

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from fast_app.core.error_responses import (
    build_app_error_response_content,
    build_internal_error_response_content,
)
from fast_app.dependencies.rag_dependencies import get_rag_pipeline
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse
from fast_app.services.exceptions import AppServiceError
from fast_app.services.conversation_scope import (
    get_request_external_session_id,
    scope_rag_chat_request,
)
from fast_app.services.knowledge_permission_policy import KnowledgePermissionPolicy
from fast_app.services.rag_pipeline_service import RagPipeline

from fast_app.core.logging import format_log_fields, get_logger
from fast_app.core.request_context import get_request_id, get_trace_id

import json
from fastapi.encoders import jsonable_encoder

logger = get_logger(__name__)

router = APIRouter(prefix="/rag", tags=["rag-chat"])
knowledge_permission_policy = KnowledgePermissionPolicy()

# pipeline: RagPipeline = Depends(get_rag_pipeline)

# 这个接口函数需要一个 RagPipeline。
# 这个 RagPipeline 不由我在函数内部手动创建。
# 请 FastAPI 在调用接口函数之前，先执行 get_rag_pipeline()。
# 然后把返回值传给 pipeline 参数
@router.post("/chat", response_model=RagChatResponse)
async def rag_chat_endpoint(
    req: RagChatRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    pipeline: RagPipeline = Depends(get_rag_pipeline),
) -> RagChatResponse:
    start_time = perf_counter()
    # 生成 scoped conversation id
    scoped_req = prepare_authorized_rag_request(req=req, user=user)
    logger.info(
        "rag_chat_request %s",
        format_log_fields(
            event="rag.chat.request.start",
            user_id=user.user_id,
            auth_source=user.auth_source,
            session_id=scoped_req.session_id,
            external_session_id=get_request_external_session_id(scoped_req),
            query=req.query,
            mode=req.mode,
            top_k=req.top_k,
            candidate_k=req.candidate_k,
            min_score=req.min_score,
        ),
    )

    try:
        response = await pipeline.run(scoped_req)
    except Exception as exc:
        latency_ms = (perf_counter() - start_time) * 1000
        logger.exception(
            "rag_chat_request %s",
            format_log_fields(
                event="rag.chat.request.failed",
                user_id=user.user_id,
                auth_source=user.auth_source,
                session_id=scoped_req.session_id,
                external_session_id=get_request_external_session_id(scoped_req),
                query=req.query,
                mode=req.mode,
                top_k=req.top_k,
                candidate_k=req.candidate_k,
                min_score=req.min_score,
                latency_ms=round(latency_ms, 2),
                error_type=type(exc).__name__,
            ),
        )
        raise

    response.request_id = get_request_id()
    response.trace_id = get_trace_id()

    latency_ms = (perf_counter() - start_time) * 1000
    logger.info(
        "rag_chat_request %s",
        format_log_fields(
            event="rag.chat.request.finish",
            user_id=user.user_id,
            auth_source=user.auth_source,
            session_id=scoped_req.session_id,
            external_session_id=get_request_external_session_id(scoped_req),
            query=req.query,
            mode=req.mode,
            top_k=req.top_k,
            candidate_k=req.candidate_k,
            min_score=req.min_score,
            latency_ms=round(latency_ms, 2),
            source_count=len(response.sources),
            answer_length=len(response.answer),
        ),
    )

    return response


# 兼容旧版 token-only SSE；当前主流式接口是 /rag/chat/stream/events。
async def rag_chat_sse_event_generator(
    req: RagChatRequest,
    pipeline: RagPipeline,
) -> AsyncGenerator[str, None]:
    try:
        async for token in pipeline.stream(req):
            yield f"data: {token}\n\n"

        yield "event: done\ndata: [DONE]\n\n"

    except AppServiceError as exc:
        yield format_sse_event(
            event="error",
            data=build_app_error_response_content(exc),
        )

    except Exception:
        logger.exception("RAG SSE 流式输出发生未知异常")
        yield format_sse_event(
            event="error",
            data=build_internal_error_response_content(),
        )




@router.post("/chat/stream", deprecated=True)
async def rag_chat_stream_endpoint(
    req: RagChatRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    pipeline: RagPipeline = Depends(get_rag_pipeline),
) -> StreamingResponse:
    scoped_req = prepare_authorized_rag_request(req=req, user=user)
    return StreamingResponse(
        rag_chat_sse_event_generator(scoped_req, pipeline),
        media_type="text/event-stream",
    )


# 流式事件格式化工具函数。
# 当前主线事件包括 sources / answer_delta / guard_sanitized / guard_blocked。
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

    except AppServiceError as exc:
        yield format_sse_event(
            event="error",
            data=build_app_error_response_content(exc),
        )

    except Exception:
        logger.exception("RAG 结构化 SSE 流式输出发生未知异常")
        yield format_sse_event(
            event="error",
            data=build_internal_error_response_content(),
        )


@router.post("/chat/stream/events")
async def rag_chat_stream_events_endpoint(
    req: RagChatRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    pipeline: RagPipeline = Depends(get_rag_pipeline),
) -> StreamingResponse:
    scoped_req = prepare_authorized_rag_request(req=req, user=user)
    return StreamingResponse(
        rag_chat_structured_sse_event_generator(scoped_req, pipeline),
        media_type="text/event-stream",
    )


def prepare_authorized_rag_request(
    req: RagChatRequest,
    user: CurrentUserContext,
) -> RagChatRequest:
    """生成带会话隔离和知识库权限 scope 的内部请求。"""

    scoped_req = scope_rag_chat_request(req=req, user=user)
    scoped_req._retrieval_permission_scope = knowledge_permission_policy.build_scope(
        user
    )
    return scoped_req

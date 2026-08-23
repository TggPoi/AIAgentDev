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
from fast_app.dependencies.document_access_dependencies import (
    get_document_access_policy,
)
from fast_app.dependencies.conversation_dependencies import (
    get_structured_conversation_turn_recorder,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse
from fast_app.schemas.rag_stream_schema import (
    RagSseEventFrame,
    normalize_and_validate_sse_event_data,
)
from fast_app.services.exceptions import AppServiceError, Nl2SqlLegacyStreamUnsupportedError
from fast_app.services.exceptions import KnowledgeVersionNotReadyError
from fast_app.dependencies.rag_dependencies import get_db_session
from fast_app.integrations.gitlab.repository import GitLabRepository
from sqlalchemy.ext.asyncio import AsyncSession
from fast_app.services.conversation.conversation_scope import (
    get_request_external_session_id,
    scope_rag_chat_request,
)
from fast_app.services.knowledge.document_access_policy import DocumentAccessPolicy
from fast_app.services.conversation.structured_turn_recorder import (
    StructuredConversationTurnRecorder,
    StructuredTurnState,
)
from fast_app.services.rag.rag_pipeline_service import RagPipeline
from fast_app.dependencies.nl2sql_dependencies import get_nl2sql_service
from fast_app.services.nl2sql.models import Nl2SqlQueryResult
from fast_app.services.nl2sql.service import Nl2SqlService

from fast_app.core.logging import format_log_fields, get_logger
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
    user: CurrentUserContext = Depends(get_current_user_context),
    pipeline: RagPipeline = Depends(get_rag_pipeline),
    session: AsyncSession = Depends(get_db_session),
    nl2sql_service: Nl2SqlService = Depends(get_nl2sql_service),
    document_access_policy: DocumentAccessPolicy = Depends(get_document_access_policy),
) -> RagChatResponse:
    start_time = perf_counter()
    if req.dataset_id is not None:
        dataset, req._nl2sql_authorization = await nl2sql_service.authorize_action(
            user=user,
            dataset_id=req.dataset_id,
            action=req.nl2sql_action or "",
        )
        # 敏感 Dataset 继续在任何 Router/普通 RAG 模型调用前执行本地标记化链路。
        # 非敏感 query 则进入现有 Agent Router，由 Router 判断数据库、知识库或复杂任务。
        if (
            req.nl2sql_action == "query"
            and dataset.privacy_classification == "sensitive"
        ):
            result = await nl2sql_service.query(
                user=user,
                dataset_id=req.dataset_id,
                question=req.query,
            )
            return RagChatResponse(
                request_id=result.request_id,
                trace_id=result.trace_id,
                query=req.query,
                answer=result.summary,
                sources=[],
                route_intent="structured_data_query",
                route_confidence=1.0,
                route_source="rule",
                nl2sql_result=result,
            )
    # 生成 scoped conversation id
    repository = GitLabRepository(session)
    scoped_req = await prepare_authorized_rag_request(
        req=req,
        user=user,
        repository=repository,
        document_access_policy=document_access_policy,
    )
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
    await annotate_rag_response_version(
        response=response,
        request=scoped_req,
        repository=repository,
    )

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
    session: AsyncSession = Depends(get_db_session),
    document_access_policy: DocumentAccessPolicy = Depends(get_document_access_policy),
) -> StreamingResponse:
    if req.dataset_id is not None:
        raise Nl2SqlLegacyStreamUnsupportedError(
            "NL2SQL 只支持 /rag/chat 或 /rag/chat/stream/events"
        )
    scoped_req = await prepare_authorized_rag_request(
        req=req,
        user=user,
        repository=GitLabRepository(session),
        document_access_policy=document_access_policy,
    )
    return StreamingResponse(
        rag_chat_sse_event_generator(scoped_req, pipeline),
        media_type="text/event-stream",
    )


# 流式事件格式化工具函数。
# 当前主线事件包括 sources / answer_delta / guard_sanitized / guard_blocked。
# sources 里包含 RagSource 这种 Pydantic model, json.dumps() 不能直接序列化 Pydantic model，所以需要先用 jsonable_encoder 转成 dict，再序列化成字符串。
def format_sse_event(event: str, data: object) -> str:
    payload = normalize_and_validate_sse_event_data(
        event,
        data,
        request_id=get_request_id(),
    )
    return (
        f"event: {event}\n"
        f"data: {json.dumps(jsonable_encoder(payload), ensure_ascii=False)}\n\n"
    )

# 结构化 SSE 生成器
async def rag_chat_structured_sse_event_generator(
    req: RagChatRequest,
    pipeline: RagPipeline,
    repository: GitLabRepository | None = None,
    turn_recorder: StructuredConversationTurnRecorder | None = None,
) -> AsyncGenerator[str, None]:
    source_doc_ids: set[str] = set()
    turn_state = StructuredTurnState()
    terminal_status = "aborted"
    provider = str(getattr(pipeline, "pipeline_provider", "unknown"))
    try:
        async for stream_event in pipeline.stream_events(req):
            turn_state.observe(stream_event.event, stream_event.data)
            if stream_event.event == "sources":
                source_doc_ids.update(
                    str(
                        source.get("doc_id")
                        if isinstance(source, dict)
                        else source.doc_id
                    )
                    for source in stream_event.data.get("sources", [])
                    if (
                        source.get("doc_id")
                        if isinstance(source, dict)
                        else getattr(source, "doc_id", None)
                    )
                )
            yield format_sse_event(
                event=stream_event.event,
                data=stream_event.data,
            )

        changed = (
            await repository.changed_doc_ids_after_version(
                req._knowledge_version or 0
            )
            if repository is not None
            else set()
        )
        stale_doc_ids = sorted(source_doc_ids & changed)
        done_data = {
            "status": "done",
            "knowledge_version": req._knowledge_version or 0,
            "stale": bool(stale_doc_ids),
            "stale_doc_ids": stale_doc_ids,
        }
        terminal_status = "completed"
        yield format_sse_event(event="done", data=done_data)

    except AppServiceError as exc:
        terminal_status = "error"
        error_data = build_app_error_response_content(exc)
        turn_state.observe("error", error_data)
        yield format_sse_event(
            event="error",
            data=error_data,
        )

    except Exception:
        terminal_status = "error"
        logger.exception("RAG 结构化 SSE 流式输出发生未知异常")
        error_data = build_internal_error_response_content()
        turn_state.observe("error", error_data)
        yield format_sse_event(
            event="error",
            data=error_data,
        )
    finally:
        if turn_recorder is not None:
            try:
                await turn_recorder.record(
                    request=req,
                    provider=provider,
                    state=turn_state,
                    terminal_status=terminal_status,
                )
            except Exception:
                logger.exception(
                    "structured stream 会话持久化失败: provider=%s session_id=%s",
                    provider,
                    req.session_id,
                )


@router.post(
    "/chat/stream/events",
    responses={
        200: {
            "description": "RagAgent 结构化 SSE；每个 data payload 包含 contract_version 和 request_id。",
            "headers": {
                "X-Request-ID": {
                    "description": "与事件 payload request_id 对齐的请求 ID。",
                    "schema": {"type": "string"},
                }
            },
            "content": {
                "text/event-stream": {
                    "schema": RagSseEventFrame.model_json_schema(),
                }
            },
        }
    },
)
async def rag_chat_stream_events_endpoint(
    req: RagChatRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    pipeline: RagPipeline = Depends(get_rag_pipeline),
    session: AsyncSession = Depends(get_db_session),
    nl2sql_service: Nl2SqlService = Depends(get_nl2sql_service),
    document_access_policy: DocumentAccessPolicy = Depends(get_document_access_policy),
    turn_recorder: StructuredConversationTurnRecorder = Depends(
        get_structured_conversation_turn_recorder
    ),
) -> StreamingResponse:
    if req.dataset_id is not None:
        dataset, req._nl2sql_authorization = await nl2sql_service.authorize_action(
            user=user,
            dataset_id=req.dataset_id,
            action=req.nl2sql_action or "",
        )
        if (
            req.nl2sql_action == "query"
            and dataset.privacy_classification == "sensitive"
        ):
            result = await nl2sql_service.query(
                user=user,
                dataset_id=req.dataset_id,
                question=req.query,
            )
            scoped_req = scope_rag_chat_request(req=req, user=user)
            scoped_req._current_user_context = user
            scoped_req._structured_turn_persistence_managed = True
            return StreamingResponse(
                nl2sql_sse_event_generator(
                    result,
                    request=scoped_req,
                    turn_recorder=turn_recorder,
                ),
                media_type="text/event-stream",
            )
    repository = GitLabRepository(session)
    scoped_req = await prepare_authorized_rag_request(
        req=req,
        user=user,
        repository=repository,
        document_access_policy=document_access_policy,
    )
    scoped_req._structured_turn_persistence_managed = True
    return StreamingResponse(
        rag_chat_structured_sse_event_generator(
            scoped_req,
            pipeline,
            repository,
            turn_recorder,
        ),
        media_type="text/event-stream",
    )


async def nl2sql_sse_event_generator(
    result: Nl2SqlQueryResult,
    request: RagChatRequest | None = None,
    turn_recorder: StructuredConversationTurnRecorder | None = None,
) -> AsyncGenerator[str, None]:
    turn_state = StructuredTurnState()
    sql_data = {
            "query_id": result.query_id,
            "dataset_id": result.dataset_id,
            "parameterized_sql": result.parameterized_sql,
            "attempt_count": result.attempt_count,
    }
    result_data = result.model_dump(mode="json")
    terminal_status = "aborted"
    try:
        yield format_sse_event(event="nl2sql_sql_generated", data=sql_data)
        turn_state.observe("nl2sql_result", result_data)
        yield format_sse_event(event="nl2sql_result", data=result_data)
        terminal_status = "completed"
        yield format_sse_event(
            event="done",
            data={"status": "done", "query_id": result.query_id},
        )
    finally:
        if request is not None and turn_recorder is not None:
            try:
                await turn_recorder.record(
                    request=request,
                    provider="nl2sql",
                    state=turn_state,
                    terminal_status=terminal_status,
                )
            except Exception:
                logger.exception(
                    "NL2SQL structured stream 会话持久化失败: session_id=%s",
                    request.session_id,
                )


async def prepare_authorized_rag_request(
    req: RagChatRequest,
    user: CurrentUserContext,
    repository: GitLabRepository,
    document_access_policy: DocumentAccessPolicy,
) -> RagChatRequest:
    """生成带会话隔离和知识库权限 scope 的内部请求。"""

    scoped_req = scope_rag_chat_request(req=req, user=user)
    scoped_req._current_user_context = user
    scoped_req._nl2sql_authorization = req._nl2sql_authorization
    scoped_req._retrieval_permission_scope = (
        await document_access_policy.build_retrieval_scope(user)
    )
    active_version = await repository.get_active_version()
    if (
        req.min_knowledge_version is not None
        and active_version < req.min_knowledge_version
    ):
        raise KnowledgeVersionNotReadyError(
            "知识库仍在更新，请等待目标版本发布后重新检索"
        )
    scoped_req._knowledge_version = active_version
    return scoped_req


async def annotate_rag_response_version(
    *,
    response: RagChatResponse,
    request: RagChatRequest,
    repository: GitLabRepository,
) -> None:
    version = request._knowledge_version or 0
    response.knowledge_version = version
    changed = await repository.changed_doc_ids_after_version(version)
    source_doc_ids = {source.doc_id for source in response.sources if source.doc_id}
    response.stale_doc_ids = sorted(source_doc_ids & changed)
    response.stale = bool(response.stale_doc_ids)

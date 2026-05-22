from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from fast_app.schemas.chat_schema import ChatRequest, ChatResponse
from fast_app.services.chat_service import chat, stream_chat


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest) -> ChatResponse:
    return await chat(req)


async def chat_sse_event_generator(
    req: ChatRequest,
) -> AsyncGenerator[str, None]:
    async for token in stream_chat(req):
        yield f"data: {token}\n\n"

    yield "event: done\ndata: [DONE]\n\n"


@router.post("/stream")
async def chat_stream_endpoint(req: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        chat_sse_event_generator(req),
        media_type="text/event-stream",
    )
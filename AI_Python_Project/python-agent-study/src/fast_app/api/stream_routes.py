import asyncio
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse


router = APIRouter(prefix="/stream", tags=["stream"])


async def simple_text_stream() -> AsyncGenerator[str, None]:
    for chunk in ["Hello", " ", "Streaming", " ", "Response"]:
        await asyncio.sleep(0.5)
        yield chunk


@router.get("/text")
async def text_stream_endpoint() -> StreamingResponse:
    return StreamingResponse(
        simple_text_stream(),
        media_type="text/plain",
    )


async def simple_sse_stream() -> AsyncGenerator[str, None]:
    for token in ["RAG", " 是", " 检索", " 增强", " 生成"]:
        await asyncio.sleep(0.5)
        yield f"data: {token}\n\n"

    yield "event: done\ndata: [DONE]\n\n"


@router.get("/sse")
async def sse_stream_endpoint() -> StreamingResponse:
    return StreamingResponse(
        simple_sse_stream(),
        media_type="text/event-stream",
    )
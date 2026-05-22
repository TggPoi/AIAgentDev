import asyncio

from fast_app.schemas.chat_schema import ChatRequest, ChatResponse
from collections.abc import AsyncGenerator


async def chat(req: ChatRequest) -> ChatResponse:
    # 模拟调用 LLM API 的网络等待
    await asyncio.sleep(0.5)

    session_id = req.session_id or "new_session"

    return ChatResponse(
        answer=f"Echo: {req.message}",
        session_id=session_id,
    )


async def stream_chat(req: ChatRequest) -> AsyncGenerator[str, None]:
    answer = f"Echo stream: {req.message}"

    for char in answer:
        await asyncio.sleep(0.05)
        yield char
import asyncio

from fast_app.schemas.chat_schema import ChatRequest, ChatResponse


async def chat(req: ChatRequest) -> ChatResponse:
    # 模拟调用 LLM API 的网络等待
    await asyncio.sleep(0.5)

    session_id = req.session_id or "new_session"

    return ChatResponse(
        answer=f"Echo: {req.message}",
        session_id=session_id,
    )
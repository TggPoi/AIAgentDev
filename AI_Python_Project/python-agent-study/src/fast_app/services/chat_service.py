from fast_app.schemas.chat_schema import ChatRequest, ChatResponse


def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or "new_session"

    return ChatResponse(
        answer=f"Echo: {req.message}",
        session_id=session_id,
    )
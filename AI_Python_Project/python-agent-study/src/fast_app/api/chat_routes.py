from fastapi import APIRouter

from fast_app.schemas.chat_schema import ChatRequest, ChatResponse
from fast_app.services.chat_service import chat


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest) -> ChatResponse:
    return await chat(req)
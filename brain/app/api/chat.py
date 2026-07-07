"""/chat — send a message to Jarvis and get a reply (conversation history persisted)."""
from fastapi import APIRouter, Depends

from app.conversation import service
from app.deps import require_token
from app.schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, _: None = Depends(require_token)) -> ChatResponse:
    reply, conversation_id = await service.handle_incoming("http", req.session_id, req.message)
    return ChatResponse(reply=reply, conversation_id=conversation_id)

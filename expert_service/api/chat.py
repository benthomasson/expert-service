"""Chat API endpoint with SSE streaming."""

from uuid import UUID, uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from expert_service.chat.loop import chat_stream

router = APIRouter(prefix="/api/projects/{project_id}", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    model: str = "gemini-2.5-pro"
    thread_id: str | None = None


@router.post("/chat")
async def chat(project_id: UUID, data: ChatRequest):
    thread_id = data.thread_id or str(uuid4())

    return StreamingResponse(
        chat_stream(project_id, data.model, data.message, thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Thread-Id": thread_id,
        },
    )

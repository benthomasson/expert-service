"""Chat API endpoint with SSE streaming."""

from uuid import UUID, uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from expert_service.chat.loop import chat_stream, dual_ask, dual_chat_stream

router = APIRouter(prefix="/api/projects/{project_id}", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    model: str = "claude-sonnet-4-6"
    thread_id: str | None = None
    dual: bool = True


@router.post("/chat")
async def chat(project_id: UUID, data: ChatRequest):
    thread_id = data.thread_id or str(uuid4())

    if data.dual:
        stream = dual_chat_stream(project_id, data.model, data.message, thread_id)
    else:
        stream = chat_stream(project_id, data.model, data.message, thread_id)

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Thread-Id": thread_id,
        },
    )


class AskRequest(BaseModel):
    question: str
    model: str = "claude-sonnet-4-6"


@router.post("/ask")
async def ask(project_id: UUID, data: AskRequest):
    """Non-streaming dual-path answer. Returns complete JSON — designed for evals."""
    return await dual_ask(project_id, data.model, data.question)

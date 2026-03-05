"""Chat API endpoint with SSE streaming."""

from uuid import UUID, uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from expert_service.chat.loop import chat_stream

router = APIRouter(prefix="/api/projects/{project_id}", tags=["chat"])

# In-memory conversation store (no persistence for v1)
_conversations: dict[str, list] = {}

SYSTEM_PROMPT = """You are an expert assistant for a domain knowledge base.
You have tools to search and read entries, beliefs, and source documents.

Guidelines:
- Always search the knowledge base before answering domain questions.
- Cite entry IDs or belief IDs when referencing specific knowledge.
- If you cannot find relevant information, say so rather than guessing.
- Be concise and direct in your answers.
- When listing beliefs, format them clearly with their IDs."""


class ChatRequest(BaseModel):
    message: str
    model: str = "gemini-2.5-pro"
    thread_id: str | None = None


@router.post("/chat")
async def chat(project_id: UUID, data: ChatRequest):
    thread_id = data.thread_id or str(uuid4())
    key = f"{project_id}:{thread_id}"

    if key not in _conversations:
        _conversations[key] = [SystemMessage(content=SYSTEM_PROMPT)]

    _conversations[key].append(HumanMessage(content=data.message))

    return StreamingResponse(
        chat_stream(_conversations[key], project_id, data.model),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Thread-Id": thread_id,
        },
    )

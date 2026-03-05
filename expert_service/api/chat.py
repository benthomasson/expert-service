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

Tool usage rules:
- SEARCH ONCE, then answer. Do not call search_knowledge or grep_content more than once per question.
- If search returns entries, read_entry ONE entry to get details, then answer. Pattern: search → read → answer.
- NEVER call the same tool twice or call two search tools. Pick ONE: search_knowledge, grep_content, or semantic_search.
- search_knowledge: keyword/concept search (default). grep_content: exact strings (commands, filenames). semantic_search: meaning-based when keywords fail.
- Do NOT narrate tool usage. No "Let me search..." — just call tools and answer.

Answer rules:
- Cite entry IDs or belief IDs when referencing knowledge.
- When information is partial, share what you found and note what's missing.
- Be concise and direct."""


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

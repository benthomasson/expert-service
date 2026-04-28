"""LangGraph agent streaming with SSE translation."""

import json
import logging
from collections.abc import AsyncGenerator
from uuid import UUID

from sqlalchemy import text as sa_text

from expert_service.chat.agent import get_agent
from expert_service.config import settings
from expert_service.db.connection import get_sync_session

logger = logging.getLogger(__name__)


def _quick_belief_search(project_id: UUID, question: str, limit: int = 10) -> str:
    """Fast belief pre-check via PostgreSQL tsvector. Returns compact format."""
    with get_sync_session() as session:
        rows = session.execute(
            sa_text(
                "SELECT id, text, truth_value "
                "FROM rms_nodes "
                "WHERE project_id = :pid "
                "AND to_tsvector('english', text) @@ plainto_tsquery('english', :q) "
                "ORDER BY ts_rank(to_tsvector('english', text), "
                "         plainto_tsquery('english', :q)) DESC "
                "LIMIT :lim"
            ),
            {"pid": str(project_id), "q": question, "lim": limit},
        ).all()

    if not rows:
        return ""
    return "\n".join(
        f"[{r.truth_value}] {r.id} — {r.text}" for r in rows
    )


def _extract_text(content) -> str:
    """Extract plain text from LLM content (handles str, list of dicts, etc.)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(content)


async def chat_stream(
    project_id: UUID,
    model: str,
    message: str,
    thread_id: str,
) -> AsyncGenerator[str, None]:
    """Stream a chat response via LangGraph react agent.

    Translates LangGraph streaming events into SSE:
      data: {"type": "token", "content": "..."}
      event: tool_call\\ndata: {"name": "...", "args": {...}}
      event: tool_result\\ndata: {"name": "...", "summary": "..."}
      event: done\\ndata: {}
    """
    agent = await get_agent(project_id, model)
    config = {"configurable": {"thread_id": f"{project_id}:{thread_id}"}}

    if settings.langfuse_secret_key:
        from langfuse.langchain import CallbackHandler

        config["callbacks"] = [CallbackHandler()]

    # Belief-first pre-check: inject matching beliefs so the LLM can
    # answer directly without a tool call when beliefs are sufficient.
    belief_context = _quick_belief_search(project_id, message)
    if belief_context:
        augmented = f"{message}\n\n[Belief matches:\n{belief_context}\n]"
        logger.info("Belief pre-check: %d matches for %r",
                     belief_context.count("\n") + 1, message[:60])
    else:
        augmented = message

    inputs = {"messages": [{"role": "user", "content": augmented}]}

    buffered_tokens: list[str] = []

    async for mode, data in agent.astream(
        inputs, config, stream_mode=["messages", "updates"]
    ):
        if mode == "messages":
            chunk, metadata = data
            # Only buffer tokens from the agent node (not tools)
            if metadata.get("langgraph_node") == "agent":
                text = _extract_text(chunk.content) if chunk.content else ""
                if text:
                    buffered_tokens.append(text)

        elif mode == "updates":
            if "agent" in data:
                msg = data["agent"]["messages"][-1]
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    # Intermediate round — suppress text, emit tool indicators
                    buffered_tokens.clear()
                    for tc in msg.tool_calls:
                        yield (
                            f"event: tool_call\n"
                            f"data: {json.dumps({'name': tc['name'], 'args': tc['args']})}\n\n"
                        )
                else:
                    # Final round — flush buffered tokens
                    for text in buffered_tokens:
                        yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"
                    buffered_tokens.clear()

            elif "tools" in data:
                for msg in data["tools"]["messages"]:
                    summary = str(msg.content)[:200]
                    name = getattr(msg, "name", "tool")
                    yield (
                        f"event: tool_result\n"
                        f"data: {json.dumps({'name': name, 'summary': summary})}\n\n"
                    )

    yield "event: done\ndata: {}\n\n"

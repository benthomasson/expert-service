"""Tool-calling chat loop with SSE streaming."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import timedelta
from uuid import UUID

from langchain_core.messages import SystemMessage, ToolMessage

from expert_service.chat.tools import make_tools
from expert_service.llm.provider import get_chat_model

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5

# Gemini context cache — keyed by model name, created once per model
_gemini_caches: dict[str, str | None] = {}


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
    messages: list,
    project_id: UUID,
    model: str,
) -> AsyncGenerator[str, None]:
    """Stream a chat response with tool-calling.

    Yields SSE-formatted events:
      data: {"type": "token", "content": "..."}
      event: tool_call\\ndata: {"name": "...", "args": {...}}
      event: tool_result\\ndata: {"name": "...", "summary": "..."}
      event: done\\ndata: {}
    """
    tools = make_tools(project_id)
    tool_map = {t.name: t for t in tools}

    # Gemini context caching — cache the system prompt server-side
    cached_content = None
    if "gemini" in model and model not in _gemini_caches:
        try:
            from langchain_google_vertexai import create_context_cache

            base_llm = get_chat_model(model)
            system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
            cache_name = create_context_cache(
                model=base_llm,
                messages=system_msgs,
                time_to_live=timedelta(hours=1),
            )
            _gemini_caches[model] = cache_name
            logger.info("Created Gemini context cache: %s", cache_name)
        except Exception as exc:
            _gemini_caches[model] = None
            logger.debug("Gemini context caching unavailable: %s", exc)

    if "gemini" in model:
        cached_content = _gemini_caches.get(model)

    if cached_content:
        llm = get_chat_model(model, cached_content=cached_content).bind_tools(tools)
        # Strip system messages — they're in the cache
        active_messages = [m for m in messages if not isinstance(m, SystemMessage)]
    else:
        llm = get_chat_model(model).bind_tools(tools)
        active_messages = messages

    for _ in range(MAX_TOOL_ROUNDS):
        # Collect full response (buffer text — only stream on final round)
        full = None
        buffered_text = []
        async for chunk in llm.astream(active_messages):
            text = _extract_text(chunk.content) if chunk.content else ""
            if text:
                buffered_text.append(text)
            full = chunk if full is None else full + chunk

        if full is None:
            break

        # Add AI message to conversation (and active list if separate)
        messages.append(full)
        if active_messages is not messages:
            active_messages.append(full)

        # If no tool calls, this is the final response — stream the buffered text
        if not full.tool_calls:
            for text in buffered_text:
                yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"
            break

        # Tool calls — emit tool indicators (suppress intermediate text)
        for tc in full.tool_calls:
            yield (
                f"event: tool_call\n"
                f"data: {json.dumps({'name': tc['name'], 'args': tc['args']})}\n\n"
            )

            # Run sync tool in thread pool
            result = await asyncio.to_thread(tool_map[tc["name"]].invoke, tc["args"])

            # Summarize result for SSE (keep it short for the UI)
            summary = str(result)[:200]
            yield (
                f"event: tool_result\n"
                f"data: {json.dumps({'name': tc['name'], 'summary': summary})}\n\n"
            )

            tool_msg = ToolMessage(content=str(result), tool_call_id=tc["id"])
            messages.append(tool_msg)
            if active_messages is not messages:
                active_messages.append(tool_msg)

    yield "event: done\ndata: {}\n\n"

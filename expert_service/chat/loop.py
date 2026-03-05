"""Tool-calling chat loop with SSE streaming."""

import asyncio
import json
from collections.abc import AsyncGenerator
from uuid import UUID

from langchain_core.messages import ToolMessage

from expert_service.chat.tools import make_tools
from expert_service.llm.provider import get_chat_model

MAX_TOOL_ROUNDS = 5


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
    llm = get_chat_model(model).bind_tools(tools)

    for _ in range(MAX_TOOL_ROUNDS):
        # Collect full response (buffer text — only stream on final round)
        full = None
        buffered_text = []
        async for chunk in llm.astream(messages):
            text = _extract_text(chunk.content) if chunk.content else ""
            if text:
                buffered_text.append(text)
            full = chunk if full is None else full + chunk

        if full is None:
            break

        # Add AI message to conversation
        messages.append(full)

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

            messages.append(
                ToolMessage(content=str(result), tool_call_id=tc["id"])
            )

    yield "event: done\ndata: {}\n\n"

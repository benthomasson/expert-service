"""Meta-expert SSE streaming loop.

Mirrors loop.py but uses the meta-agent instead of project-scoped agents.
Same SSE protocol: token, tool_call, tool_result, done.
"""

import json
import logging
from collections.abc import AsyncGenerator

from expert_service.chat.loop import _extract_text
from expert_service.chat.meta_agent import get_meta_agent
from expert_service.config import settings

logger = logging.getLogger(__name__)


async def meta_chat_stream(
    model: str,
    message: str,
    thread_id: str,
) -> AsyncGenerator[str, None]:
    """Stream a meta-expert chat response via SSE."""
    agent = await get_meta_agent(model)
    config = {"configurable": {"thread_id": f"meta:{thread_id}"}}

    if settings.langfuse_secret_key:
        from langfuse.langchain import CallbackHandler

        config["callbacks"] = [CallbackHandler()]

    inputs = {"messages": [{"role": "user", "content": message}]}
    buffered_tokens: list[str] = []

    async for mode, data in agent.astream(
        inputs, config, stream_mode=["messages", "updates"]
    ):
        if mode == "messages":
            chunk, metadata = data
            if metadata.get("langgraph_node") == "agent":
                text = _extract_text(chunk.content) if chunk.content else ""
                if text:
                    buffered_tokens.append(text)

        elif mode == "updates":
            if "agent" in data:
                msg = data["agent"]["messages"][-1]
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    buffered_tokens.clear()
                    for tc in msg.tool_calls:
                        yield (
                            f"event: tool_call\n"
                            f"data: {json.dumps({'name': tc['name'], 'args': tc['args']})}\n\n"
                        )
                else:
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

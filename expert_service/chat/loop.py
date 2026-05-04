"""LangGraph agent streaming with SSE translation."""

import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator
from uuid import UUID

from sqlalchemy import text as sa_text

from expert_service.chat.agent import get_agent
from expert_service.config import settings
from expert_service.db.connection import get_sync_session
from expert_service.llm.provider import get_chat_model

logger = logging.getLogger(__name__)

# Common stop words to exclude from OR queries (matches reasons_lib)
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "ought",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
    "they", "them", "their", "this", "that", "these", "those", "what",
    "which", "who", "whom", "how", "when", "where", "why", "if", "then",
    "than", "so", "no", "not", "only", "very", "too", "also", "just",
    "about", "above", "after", "before", "between", "but", "by", "for",
    "from", "in", "into", "of", "on", "or", "out", "over", "to", "up",
    "with", "and", "as", "at",
})


def _build_or_tsquery(question: str) -> str:
    """Build an OR-based tsquery string from a question, matching FTS5 behavior."""
    words = re.findall(r'\w+', question)
    words = [w for w in words if w.lower() not in _STOP_WORDS and len(w) > 1]
    if not words:
        words = [w for w in re.findall(r'\w+', question) if len(w) > 1]
    if not words:
        return ""
    return " | ".join(w for w in words)


def _quick_belief_search(project_id: UUID, question: str, limit: int = 10) -> str:
    """Fast belief pre-check via PostgreSQL tsvector (OR matching). Returns compact format."""
    or_query = _build_or_tsquery(question)
    if not or_query:
        return ""
    with get_sync_session() as session:
        rows = session.execute(
            sa_text(
                "SELECT id, text, truth_value "
                "FROM rms_nodes "
                "WHERE project_id = :pid "
                "AND to_tsvector('english', text) @@ to_tsquery('english', :q) "
                "ORDER BY ts_rank(to_tsvector('english', text), "
                "         to_tsquery('english', :q)) DESC "
                "LIMIT :lim"
            ),
            {"pid": str(project_id), "q": or_query, "lim": limit},
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


# --- Dual-path architecture ---

MAX_CHUNK_CHARS = 2000  # Truncate individual chunks
MAX_CONTEXT_CHARS = 30000  # Total context budget (~7500 tokens)


def _search_source_chunks(project_id: UUID, query: str, limit: int = 10) -> str:
    """FTS search over source_chunks (OR matching). Returns formatted top-N chunks within token budget."""
    or_query = _build_or_tsquery(query)
    if not or_query:
        return ""
    with get_sync_session() as session:
        rows = session.execute(
            sa_text(
                "SELECT c.text, c.section, s.slug "
                "FROM source_chunks c "
                "JOIN sources s ON s.id = c.source_id "
                "WHERE c.project_id = :pid "
                "AND to_tsvector('english', c.text) @@ to_tsquery('english', :q) "
                "ORDER BY ts_rank(to_tsvector('english', c.text), "
                "         to_tsquery('english', :q)) DESC "
                "LIMIT :lim"
            ),
            {"pid": str(project_id), "q": or_query, "lim": limit},
        ).all()
    if not rows:
        return ""
    parts = []
    total = 0
    for i, r in enumerate(rows, 1):
        chunk_text = r.text[:MAX_CHUNK_CHARS]
        if len(r.text) > MAX_CHUNK_CHARS:
            chunk_text += "\n[...truncated]"
        header = f"[{i}] {r.slug}"
        if r.section:
            header += f" > {r.section}"
        part = f"### {header}\n\n{chunk_text}"
        if total + len(part) > MAX_CONTEXT_CHARS:
            break
        parts.append(part)
        total += len(part)
    return "\n\n---\n\n".join(parts)


TMS_ASK_PROMPT = """\
You are answering a question using a belief network (a Truth Maintenance System).
Each belief has an ID, text, and truth value (IN = held true, OUT = retracted).

Rules:
- Cite belief IDs in [brackets] when referencing specific beliefs.
- ONLY answer based on the beliefs provided. Do NOT use your training data or
  general knowledge to fill gaps.
- If the beliefs are insufficient to answer, say so honestly and note what's missing.
- Be specific and concise.

## Question

{question}

## Belief matches

{beliefs}
"""

FTS_RAG_PROMPT = """\
You are answering questions using retrieved document excerpts.

Below are the most relevant excerpts from source documents, retrieved via
full-text search. Use them to answer the question. Cite your sources by referencing
the document filename in [brackets].

If the excerpts don't contain enough information to answer the question, say so honestly.
Do not fabricate information that isn't in the provided excerpts.

## Retrieved Documents

{context}

## Question

{question}

## Instructions

- Answer the question based on the retrieved documents above
- Cite sources using [filename] notation
- If information is insufficient, say what you can and note the gaps
- Be specific and concise
"""

MERGE_PROMPT = """\
You are merging two answers to the same question. Each answer was produced
independently using a different retrieval method:

- Answer A used a structured belief network with dependency chains
- Answer B used full-text search over source documents

Produce a single merged answer that:
- Combines information from both answers
- When both answers cover the same point, use the more specific/detailed version
- Preserve all citations (belief IDs in [brackets] from Answer A, [filenames] from Answer B)
- Do not add information that neither answer contains
- If the answers contradict each other, note the disagreement

## Question

{question}

## Answer A (Belief Network)

{answer_tms}

## Answer B (Source Documents)

{answer_fts}
"""


async def dual_ask(
    project_id: UUID,
    model: str,
    message: str,
) -> dict:
    """Dual-path: TMS + FTS RAG in parallel, merge, return complete answer as dict."""
    # Phase 1: parallel retrieval
    belief_ctx, chunk_ctx = await asyncio.gather(
        asyncio.to_thread(_quick_belief_search, project_id, message, 20),
        asyncio.to_thread(_search_source_chunks, project_id, message, 10),
    )

    if not belief_ctx and not chunk_ctx:
        return {
            "answer": "No matching beliefs or source documents found for this question.",
            "tms_chars": 0,
            "rag_chars": 0,
        }

    # Phase 2: parallel synthesis
    llm = get_chat_model(model)

    async def _tms_answer() -> str:
        if not belief_ctx:
            return "No matching beliefs found in the network."
        prompt = TMS_ASK_PROMPT.format(beliefs=belief_ctx, question=message)
        resp = await llm.ainvoke(prompt)
        return _extract_text(resp.content)

    async def _rag_answer() -> str:
        if not chunk_ctx:
            return "No relevant source documents found."
        prompt = FTS_RAG_PROMPT.format(context=chunk_ctx, question=message)
        resp = await llm.ainvoke(prompt)
        return _extract_text(resp.content)

    answer_tms, answer_fts = await asyncio.gather(_tms_answer(), _rag_answer())

    # Phase 3: merge
    merge_prompt = MERGE_PROMPT.format(
        question=message, answer_tms=answer_tms, answer_fts=answer_fts,
    )
    resp = await llm.ainvoke(merge_prompt)
    merged = _extract_text(resp.content)

    return {
        "answer": merged,
        "tms_chars": len(answer_tms),
        "rag_chars": len(answer_fts),
    }


async def dual_chat_stream(
    project_id: UUID,
    model: str,
    message: str,
    thread_id: str,
) -> AsyncGenerator[str, None]:
    """Dual-path: TMS beliefs + FTS RAG in parallel, then merge with streaming.

    Three phases:
    1. Parallel retrieval: tsvector search over beliefs and source chunks
    2. Parallel synthesis: TMS answer + FTS RAG answer (two LLM calls)
    3. Merge: combine both answers in a third LLM call, streaming tokens
    """
    yield f"event: phase\ndata: {json.dumps({'phase': 'searching'})}\n\n"

    # Phase 1: parallel retrieval (sync → run in threads)
    belief_ctx, chunk_ctx = await asyncio.gather(
        asyncio.to_thread(_quick_belief_search, project_id, message, 20),
        asyncio.to_thread(_search_source_chunks, project_id, message, 10),
    )

    if not belief_ctx and not chunk_ctx:
        yield (
            f"data: {json.dumps({'type': 'token', 'content': 'No matching beliefs or source documents found for this question.'})}\n\n"
        )
        yield "event: done\ndata: {}\n\n"
        return

    # Phase 2: parallel synthesis
    yield f"event: phase\ndata: {json.dumps({'phase': 'synthesizing'})}\n\n"

    llm = get_chat_model(model)

    async def _tms_answer() -> str:
        if not belief_ctx:
            return "No matching beliefs found in the network."
        prompt = TMS_ASK_PROMPT.format(beliefs=belief_ctx, question=message)
        resp = await llm.ainvoke(prompt)
        return _extract_text(resp.content)

    async def _rag_answer() -> str:
        if not chunk_ctx:
            return "No relevant source documents found."
        prompt = FTS_RAG_PROMPT.format(context=chunk_ctx, question=message)
        resp = await llm.ainvoke(prompt)
        return _extract_text(resp.content)

    answer_tms, answer_fts = await asyncio.gather(_tms_answer(), _rag_answer())

    logger.info(
        "Dual-path: TMS=%d chars, RAG=%d chars for %r",
        len(answer_tms), len(answer_fts), message[:60],
    )

    # Phase 3: merge — stream tokens
    yield f"event: phase\ndata: {json.dumps({'phase': 'merging'})}\n\n"

    merge_prompt = MERGE_PROMPT.format(
        question=message, answer_tms=answer_tms, answer_fts=answer_fts,
    )
    async for chunk in llm.astream(merge_prompt):
        text = _extract_text(chunk.content) if chunk.content else ""
        if text:
            yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"

    yield "event: done\ndata: {}\n\n"

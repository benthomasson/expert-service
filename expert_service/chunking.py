"""Chunk markdown documents for FTS RAG."""

import re


def chunk_markdown(content: str, max_chars: int = 1000) -> list[dict]:
    """Split markdown into chunks by ## headers, then paragraphs at ~max_chars.

    Returns list of {"section": str, "text": str, "chunk_index": int}.
    """
    # Split on ## headers, keeping the header text
    parts = re.split(r"^(##\s+.+)$", content, flags=re.MULTILINE)

    chunks: list[dict] = []
    current_section = ""

    for part in parts:
        if part.startswith("## "):
            current_section = part.lstrip("# ").strip()
            continue

        # Split long sections by double newlines (paragraphs)
        paragraphs = part.split("\n\n")
        buffer = ""
        for para in paragraphs:
            if len(buffer) + len(para) > max_chars and buffer.strip():
                chunks.append({
                    "section": current_section,
                    "text": buffer.strip(),
                    "chunk_index": len(chunks),
                })
                buffer = para
            else:
                buffer = buffer + "\n\n" + para if buffer else para
        if buffer.strip():
            chunks.append({
                "section": current_section,
                "text": buffer.strip(),
                "chunk_index": len(chunks),
            })

    return chunks

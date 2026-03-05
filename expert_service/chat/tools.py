"""LangChain tools for knowledge base access, scoped per project."""

import json
from uuid import UUID

from langchain_core.tools import tool
from sqlalchemy import select, text

from expert_service.db.connection import get_sync_session
from expert_service.db.models import Claim, Entry, Source


def make_tools(project_id: UUID) -> list:
    """Create tools scoped to a specific project. The LLM never sees the project UUID."""

    @tool
    def search_knowledge(query: str) -> str:
        """Search entries and beliefs by keyword. Use this first to find relevant information before reading full entries."""
        with get_sync_session() as session:
            # Search entries via FTS
            entry_rows = session.execute(
                select(Entry.id, Entry.title, Entry.topic)
                .where(
                    Entry.project_id == project_id,
                    text(
                        "to_tsvector('english', coalesce(title, '') || ' ' || content) "
                        "@@ plainto_tsquery('english', :q)"
                    ),
                )
                .params(q=query)
                .limit(10)
            ).all()

            # Search claims via FTS
            claim_rows = session.execute(
                select(Claim.id, Claim.text, Claim.status)
                .where(
                    Claim.project_id == project_id,
                    text("to_tsvector('english', text) @@ plainto_tsquery('english', :q)"),
                )
                .params(q=query)
                .limit(10)
            ).all()

        results = {
            "entries": [
                {"id": r.id, "title": r.title, "topic": r.topic} for r in entry_rows
            ],
            "claims": [
                {"id": r.id, "text": r.text, "status": r.status} for r in claim_rows
            ],
        }
        if not results["entries"] and not results["claims"]:
            return f"No results found for '{query}'. Try different keywords."
        return json.dumps(results, indent=2)

    @tool
    def read_entry(entry_id: str) -> str:
        """Read the full content of a specific entry by its ID. Use search_knowledge first to find entry IDs."""
        with get_sync_session() as session:
            entry = session.execute(
                select(Entry).where(
                    Entry.project_id == project_id, Entry.id == entry_id
                )
            ).scalar_one_or_none()

        if not entry:
            return f"Entry '{entry_id}' not found."
        return json.dumps(
            {
                "id": entry.id,
                "topic": entry.topic,
                "title": entry.title,
                "content": entry.content,
            },
            indent=2,
        )

    @tool
    def list_entries(topic: str = "") -> str:
        """List available entries. Optionally filter by topic keyword. Returns IDs and titles (not full content)."""
        with get_sync_session() as session:
            q = select(Entry.id, Entry.topic, Entry.title).where(
                Entry.project_id == project_id
            )
            if topic:
                q = q.where(Entry.topic.ilike(f"%{topic}%"))
            rows = session.execute(q.order_by(Entry.topic).limit(50)).all()

        entries = [{"id": r.id, "topic": r.topic, "title": r.title} for r in rows]
        return json.dumps(entries, indent=2)

    @tool
    def list_beliefs(status: str = "IN") -> str:
        """List beliefs/claims in the knowledge base. Filter by status: IN (accepted), OUT (rejected), STALE, PROPOSED."""
        with get_sync_session() as session:
            rows = session.execute(
                select(Claim.id, Claim.text, Claim.status, Claim.source)
                .where(Claim.project_id == project_id, Claim.status == status)
                .order_by(Claim.id)
                .limit(50)
            ).all()

        claims = [
            {"id": r.id, "text": r.text, "status": r.status, "source": r.source}
            for r in rows
        ]
        total_note = f" (showing first 50)" if len(claims) == 50 else ""
        return f"{len(claims)} beliefs with status={status}{total_note}:\n" + json.dumps(
            claims, indent=2
        )

    @tool
    def read_source(slug: str) -> str:
        """Read a source document by its slug. Sources are the raw fetched documentation. Content is truncated to 8000 chars."""
        with get_sync_session() as session:
            source = session.execute(
                select(Source).where(
                    Source.project_id == project_id, Source.slug == slug
                )
            ).scalar_one_or_none()

        if not source:
            return f"Source '{slug}' not found."

        content = source.content
        truncated = ""
        if len(content) > 8000:
            content = content[:8000]
            truncated = "\n\n[Content truncated — original was longer]"

        return json.dumps(
            {
                "slug": source.slug,
                "url": source.url,
                "word_count": source.word_count,
                "content": content + truncated,
            },
            indent=2,
        )

    return [search_knowledge, read_entry, list_entries, list_beliefs, read_source]

"""Embedding generation and storage using fastembed + pgvector."""

from uuid import UUID

from fastembed import TextEmbedding
from sqlalchemy import delete, select

from expert_service.db.connection import get_sync_session
from expert_service.db.models import Claim, Embedding, Entry, Source

EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# Lazy-loaded model singleton
_model = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(EMBED_MODEL)
    return _model


def build_embeddings(project_id: UUID) -> dict[str, int]:
    """Build embeddings for all entries, claims, and sources in a project.

    Deletes existing embeddings for the project first (idempotent).
    Returns counts of embedded items by type.
    """
    model = _get_model()

    with get_sync_session() as session:
        # Clear existing embeddings for this project
        session.execute(
            delete(Embedding).where(Embedding.project_id == project_id)
        )

        # Gather texts to embed
        items = []  # (source_table, source_id, label, text)

        # Entries: title + content
        entries = session.execute(
            select(Entry.id, Entry.title, Entry.content)
            .where(Entry.project_id == project_id)
        ).all()
        for e in entries:
            text = f"{e.title}. {e.content}" if e.title else e.content
            items.append(("entries", e.id, e.title or e.id, text))

        # Claims: claim text
        claims = session.execute(
            select(Claim.id, Claim.text)
            .where(Claim.project_id == project_id)
        ).all()
        for c in claims:
            items.append(("claims", c.id, c.text[:80], c.text))

        # Sources: slug + truncated content
        sources = session.execute(
            select(Source.slug, Source.content)
            .where(Source.project_id == project_id)
        ).all()
        for s in sources:
            text = f"{s.slug}. {s.content[:2000]}"
            items.append(("sources", s.slug, s.slug, text))

        if not items:
            return {"entries": 0, "claims": 0, "sources": 0}

        # Batch embed all texts
        texts = [item[3] for item in items]
        vectors = list(model.embed(texts))

        # Store embeddings
        for (source_table, source_id, label, _text), vector in zip(items, vectors):
            session.add(Embedding(
                project_id=project_id,
                source_table=source_table,
                source_id=source_id,
                label=label,
                embedding=vector.tolist(),
            ))

        session.commit()

    counts = {"entries": len(entries), "claims": len(claims), "sources": len(sources)}
    return counts


def embed_query(query: str) -> list[float]:
    """Embed a single query string. Returns vector as list of floats."""
    model = _get_model()
    vectors = list(model.embed([query]))
    return vectors[0].tolist()

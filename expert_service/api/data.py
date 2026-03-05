"""Data access API routes — sources, entries, claims, search."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from expert_service.db.connection import get_session
from expert_service.db.models import Claim, Entry, Nogood, Source

router = APIRouter(prefix="/api/projects/{project_id}", tags=["data"])


@router.get("/sources")
async def list_sources(project_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Source.id, Source.slug, Source.url, Source.word_count, Source.fetched_at)
        .where(Source.project_id == project_id)
        .order_by(Source.fetched_at.desc())
    )
    return [dict(r._mapping) for r in result.all()]


@router.get("/entries")
async def list_entries(
    project_id: UUID,
    topic: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    q = select(Entry.id, Entry.topic, Entry.title, Entry.created_at).where(
        Entry.project_id == project_id
    )
    if topic:
        q = q.where(Entry.topic == topic)
    result = await session.execute(q.order_by(Entry.created_at.desc()))
    return [dict(r._mapping) for r in result.all()]


@router.get("/entries/{entry_id}")
async def get_entry(project_id: UUID, entry_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Entry).where(Entry.project_id == project_id, Entry.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        return {"error": "Entry not found"}
    return {
        "id": entry.id,
        "topic": entry.topic,
        "title": entry.title,
        "content": entry.content,
        "created_at": entry.created_at.isoformat(),
    }


@router.get("/claims")
async def list_claims(
    project_id: UUID,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    q = select(Claim).where(Claim.project_id == project_id)
    if status:
        q = q.where(Claim.status == status)
    result = await session.execute(q.order_by(Claim.created_at.desc()))
    claims = result.scalars().all()
    return [
        {
            "id": c.id,
            "text": c.text,
            "status": c.status,
            "source": c.source,
            "review_status": c.review_status,
            "created_at": c.created_at.isoformat(),
        }
        for c in claims
    ]


@router.get("/nogoods")
async def list_nogoods(project_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Nogood).where(Nogood.project_id == project_id).order_by(Nogood.discovered_at.desc())
    )
    nogoods = result.scalars().all()
    return [
        {
            "id": n.id,
            "description": n.description,
            "resolution": n.resolution,
            "claim_ids": n.claim_ids,
            "discovered_at": n.discovered_at.isoformat(),
        }
        for n in nogoods
    ]


@router.get("/search")
async def search(
    project_id: UUID,
    q: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_session),
):
    """Full-text search across entries and claims."""
    ts_query = func.plainto_tsquery("english", q)

    # Search entries
    entry_results = await session.execute(
        select(Entry.id, Entry.title, Entry.topic)
        .where(
            Entry.project_id == project_id,
            text("to_tsvector('english', coalesce(title, '') || ' ' || content) @@ plainto_tsquery('english', :q)"),
        )
        .params(q=q)
        .limit(20)
    )

    # Search claims
    claim_results = await session.execute(
        select(Claim.id, Claim.text, Claim.status)
        .where(
            Claim.project_id == project_id,
            text("to_tsvector('english', text) @@ plainto_tsquery('english', :q)"),
        )
        .params(q=q)
        .limit(20)
    )

    return {
        "entries": [dict(r._mapping) for r in entry_results.all()],
        "claims": [dict(r._mapping) for r in claim_results.all()],
    }

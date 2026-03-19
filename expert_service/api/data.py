"""Data access API routes — sources, entries, claims, search."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from expert_service.db.connection import get_session
from expert_service.db.models import Entry, Source, entry_sources
from expert_service.rms import api as rms_api

router = APIRouter(prefix="/api/projects/{project_id}", tags=["data"])


@router.get("/sources")
async def list_sources(project_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Source.id, Source.slug, Source.url, Source.word_count, Source.fetched_at)
        .where(Source.project_id == project_id)
        .order_by(Source.fetched_at.desc())
    )
    return [dict(r._mapping) for r in result.all()]


@router.get("/sources/{slug}")
async def get_source(project_id: UUID, slug: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Source).where(Source.project_id == project_id, Source.slug == slug)
    )
    source = result.scalar_one_or_none()
    if not source:
        return {"error": "Source not found"}
    # Count linked entries
    entry_count_result = await session.execute(
        select(func.count()).select_from(entry_sources).where(
            entry_sources.c.source_id == source.id
        )
    )
    return {
        "slug": source.slug,
        "url": source.url,
        "word_count": source.word_count,
        "entry_count": entry_count_result.scalar(),
        "fetched_at": source.fetched_at.isoformat() if source.fetched_at else None,
    }


@router.get("/sources/{slug}/entries")
async def list_source_entries(
    project_id: UUID, slug: str, session: AsyncSession = Depends(get_session)
):
    """List all entries linked to a source."""
    source = await session.execute(
        select(Source.id).where(Source.project_id == project_id, Source.slug == slug)
    )
    source_id = source.scalar_one_or_none()
    if source_id is None:
        return {"error": "Source not found"}
    result = await session.execute(
        select(Entry.id, Entry.topic, Entry.title, Entry.created_at)
        .join(entry_sources, (entry_sources.c.entry_id == Entry.id) & (entry_sources.c.entry_project_id == Entry.project_id))
        .where(entry_sources.c.source_id == source_id)
        .order_by(Entry.created_at.desc())
    )
    return [dict(r._mapping) for r in result.all()]


@router.get("/entries")
async def list_entries(
    project_id: UUID,
    topic: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    q = select(Entry).options(selectinload(Entry.sources)).where(
        Entry.project_id == project_id
    )
    if topic:
        q = q.where(Entry.topic == topic)
    result = await session.execute(q.order_by(Entry.created_at.desc()))
    entries = result.scalars().all()
    return [
        {
            "id": e.id,
            "topic": e.topic,
            "title": e.title,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "source_slugs": [s.slug for s in e.sources],
        }
        for e in entries
    ]


@router.get("/entries/{entry_id}")
async def get_entry(project_id: UUID, entry_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Entry)
        .options(selectinload(Entry.sources))
        .where(Entry.project_id == project_id, Entry.id == entry_id)
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
        "sources": [
            {"slug": s.slug, "url": s.url, "word_count": s.word_count}
            for s in entry.sources
        ],
    }


@router.get("/beliefs")
async def list_beliefs(
    project_id: UUID,
    status: str | None = None,
):
    result = await asyncio.to_thread(
        rms_api.list_nodes, project_id, status=status
    )
    return result


@router.get("/beliefs/status")
async def beliefs_status(project_id: UUID):
    result = await asyncio.to_thread(rms_api.get_status, project_id)
    return result


@router.get("/beliefs/{node_id}")
async def get_belief(project_id: UUID, node_id: str):
    result = await asyncio.to_thread(rms_api.show_node, project_id, node_id)
    return result


@router.get("/beliefs/{node_id}/explain")
async def explain_belief(project_id: UUID, node_id: str):
    result = await asyncio.to_thread(rms_api.explain_node, project_id, node_id)
    return result


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

    # Search RMS beliefs
    belief_results = await session.execute(
        text(
            "SELECT id, text, truth_value FROM rms_nodes "
            "WHERE project_id = :pid "
            "AND to_tsvector('english', text) @@ plainto_tsquery('english', :q) "
            "LIMIT 20"
        ),
        {"pid": str(project_id), "q": q},
    )

    return {
        "entries": [dict(r._mapping) for r in entry_results.all()],
        "beliefs": [dict(r._mapping) for r in belief_results.all()],
    }


# --- Import endpoints ---


class SourceImport(BaseModel):
    slug: str
    url: str | None = None
    content: str
    word_count: int | None = None


class SourcesImportRequest(BaseModel):
    sources: list[SourceImport]


class EntryImport(BaseModel):
    id: str
    topic: str
    title: str | None = None
    content: str
    path: str | None = None


class EntriesImportRequest(BaseModel):
    entries: list[EntryImport]


class ClaimImport(BaseModel):
    id: str
    text: str
    status: str = "IN"
    source: str | None = None
    source_hash: str | None = None


class ClaimsImportRequest(BaseModel):
    claims: list[ClaimImport]


@router.post("/import/sources")
async def import_sources(
    project_id: UUID,
    data: SourcesImportRequest,
    session: AsyncSession = Depends(get_session),
):
    """Bulk import sources from a file-based expert repo."""
    imported = 0
    skipped = 0

    for s in data.sources:
        existing = await session.execute(
            select(Source.id).where(Source.project_id == project_id, Source.slug == s.slug)
        )
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue

        source = Source(
            project_id=project_id,
            slug=s.slug,
            url=s.url,
            content=s.content,
            word_count=s.word_count,
        )
        session.add(source)
        imported += 1

    await session.commit()
    return {"imported": imported, "skipped": skipped}


@router.post("/import/entries")
async def import_entries(
    project_id: UUID,
    data: EntriesImportRequest,
    session: AsyncSession = Depends(get_session),
):
    """Bulk import entries from a file-based expert repo."""
    imported = 0
    skipped = 0
    linked = 0

    # Pre-load source slug→id map for auto-matching
    source_result = await session.execute(
        select(Source.slug, Source.id).where(Source.project_id == project_id)
    )
    source_map = {row.slug: row.id for row in source_result.all()}

    for e in data.entries:
        # Check if already exists
        existing = await session.execute(
            select(Entry.id).where(Entry.project_id == project_id, Entry.id == e.id)
        )
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue

        entry = Entry(
            id=e.id,
            project_id=project_id,
            topic=e.topic,
            title=e.title,
            content=e.content,
            metadata_={"imported_from": e.path} if e.path else None,
        )
        session.add(entry)
        imported += 1

        # Auto-match entry to source by topic == slug
        if e.topic in source_map:
            await session.execute(
                insert(entry_sources).values(
                    entry_id=e.id,
                    entry_project_id=project_id,
                    source_id=source_map[e.topic],
                )
            )
            linked += 1

    await session.commit()
    return {"imported": imported, "skipped": skipped, "linked": linked}


@router.post("/import/beliefs")
async def import_beliefs(
    project_id: UUID,
    data: ClaimsImportRequest,
):
    """Bulk import beliefs into RMS from a file-based expert repo."""

    def _do_import():
        imported = 0
        skipped = 0

        # Check existing nodes
        existing_status = rms_api.get_status(project_id)
        existing_ids = {n["id"] for n in existing_status["nodes"]}

        for c in data.claims:
            if c.id in existing_ids:
                skipped += 1
                continue

            rms_api.add_node(
                project_id,
                node_id=c.id,
                text=c.text,
                source=c.source or "",
            )

            # Match original status
            if c.status == "OUT":
                rms_api.retract_node(project_id, c.id)

            imported += 1

        return {"imported": imported, "skipped": skipped}

    return await asyncio.to_thread(_do_import)


@router.post("/link-entries-sources")
async def link_entries_sources(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Backfill entry-source links by matching entry.topic to source.slug.

    Also migrates any existing source_id FK values into the join table.
    """
    linked = 0
    already_linked = 0
    migrated = 0

    # 1. Migrate existing source_id FK values into join table
    entries_with_fk = await session.execute(
        select(Entry.id, Entry.project_id, Entry.source_id)
        .where(Entry.project_id == project_id, Entry.source_id.isnot(None))
    )
    for row in entries_with_fk.all():
        existing = await session.execute(
            select(entry_sources.c.source_id).where(
                entry_sources.c.entry_id == row.id,
                entry_sources.c.entry_project_id == row.project_id,
                entry_sources.c.source_id == row.source_id,
            )
        )
        if existing.scalar_one_or_none() is None:
            await session.execute(
                insert(entry_sources).values(
                    entry_id=row.id,
                    entry_project_id=row.project_id,
                    source_id=row.source_id,
                )
            )
            migrated += 1

    # 2. Auto-match unlinked entries by topic == slug
    source_result = await session.execute(
        select(Source.slug, Source.id).where(Source.project_id == project_id)
    )
    source_map = {row.slug: row.id for row in source_result.all()}

    all_entries = await session.execute(
        select(Entry.id, Entry.project_id, Entry.topic)
        .where(Entry.project_id == project_id)
    )
    for row in all_entries.all():
        if row.topic not in source_map:
            continue
        # Check if link already exists
        existing = await session.execute(
            select(entry_sources.c.source_id).where(
                entry_sources.c.entry_id == row.id,
                entry_sources.c.entry_project_id == row.project_id,
                entry_sources.c.source_id == source_map[row.topic],
            )
        )
        if existing.scalar_one_or_none() is not None:
            already_linked += 1
            continue
        await session.execute(
            insert(entry_sources).values(
                entry_id=row.id,
                entry_project_id=row.project_id,
                source_id=source_map[row.topic],
            )
        )
        linked += 1

    await session.commit()
    return {"linked": linked, "migrated": migrated, "already_linked": already_linked}

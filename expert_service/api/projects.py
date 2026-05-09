"""Project CRUD API routes."""

import asyncio
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from expert_service.db.connection import get_session
from expert_service.db.models import Entry, Project, Source
from expert_service.chat.meta_agent import invalidate_meta_cache
from expert_service.rms import api as rms_api

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    domain: str
    config: dict = {}


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    domain: str
    config: dict
    created_at: str
    source_count: int = 0
    entry_count: int = 0
    belief_count: int = 0

    model_config = {"from_attributes": True}


@router.post("", response_model=ProjectResponse)
async def create_project(data: ProjectCreate, session: AsyncSession = Depends(get_session)):
    project = Project(name=data.name, domain=data.domain, config=data.config)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    invalidate_meta_cache()
    return ProjectResponse(
        id=project.id,
        name=project.name,
        domain=project.domain,
        config=project.config or {},
        created_at=project.created_at.isoformat(),
    )


async def _project_counts(session: AsyncSession, project_id):
    """Get source, entry, and belief counts for a project."""
    src = await session.execute(select(func.count()).where(Source.project_id == project_id))
    ent = await session.execute(select(func.count()).where(Entry.project_id == project_id))
    blf = await asyncio.to_thread(rms_api.count_beliefs, project_id, None)
    return src.scalar() or 0, ent.scalar() or 0, blf


@router.get("")
async def list_projects(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    projects = result.scalars().all()
    responses = []
    for p in projects:
        sc, ec, cc = await _project_counts(session, p.id)
        responses.append(ProjectResponse(
            id=p.id,
            name=p.name,
            domain=p.domain,
            config=p.config or {},
            created_at=p.created_at.isoformat(),
            source_count=sc,
            entry_count=ec,
            belief_count=cc,
        ))
    return responses


@router.get("/{project_id}")
async def get_project(project_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    sc, ec, cc = await _project_counts(session, project.id)
    return ProjectResponse(
        id=project.id,
        name=project.name,
        domain=project.domain,
        config=project.config or {},
        created_at=project.created_at.isoformat(),
        source_count=sc,
        entry_count=ec,
        belief_count=cc,
    )


@router.delete("/{project_id}")
async def delete_project(project_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await session.delete(project)
    await session.commit()
    invalidate_meta_cache()
    return {"status": "deleted"}


@router.post("/import-reasons")
async def import_reasons(
    name: str = Form(...),
    domain: str = Form(""),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Import a reasons.db file to create a new project with beliefs.

    Creates the project, then imports the network via rms_api.import_network.
    """
    # Save upload to temp file for validation and import
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        content = await file.read()
        tmp.write(content)

    try:
        # Verify it's a valid reasons_lib database
        from reasons_lib.storage import Storage
        store = Storage(str(tmp_path))
        network = store.load()
        store.close()

        # Create the project
        project = Project(name=name, domain=domain)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        # Import via public API
        result = await asyncio.to_thread(
            rms_api.import_network, project.id, network
        )
        invalidate_meta_cache()

        return {
            "project_id": str(project.id),
            "name": project.name,
            "beliefs": result["node_count"],
            "nogoods": result["nogood_count"],
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Invalid reasons.db: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)

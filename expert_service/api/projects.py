"""Project CRUD API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from expert_service.db.connection import get_session
from expert_service.db.models import Project

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
    claim_count: int = 0

    model_config = {"from_attributes": True}


@router.post("", response_model=ProjectResponse)
async def create_project(data: ProjectCreate, session: AsyncSession = Depends(get_session)):
    project = Project(name=data.name, domain=data.domain, config=data.config)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return ProjectResponse(
        id=project.id,
        name=project.name,
        domain=project.domain,
        config=project.config or {},
        created_at=project.created_at.isoformat(),
    )


@router.get("")
async def list_projects(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    projects = result.scalars().all()
    return [
        ProjectResponse(
            id=p.id,
            name=p.name,
            domain=p.domain,
            config=p.config or {},
            created_at=p.created_at.isoformat(),
        )
        for p in projects
    ]


@router.get("/{project_id}")
async def get_project(project_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse(
        id=project.id,
        name=project.name,
        domain=project.domain,
        config=project.config or {},
        created_at=project.created_at.isoformat(),
    )


@router.delete("/{project_id}")
async def delete_project(project_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await session.delete(project)
    await session.commit()
    return {"status": "deleted"}

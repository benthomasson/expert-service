"""FastAPI application — API + web UI for expert-service."""

import asyncio
from pathlib import Path
from uuid import UUID

import uvicorn
from fastapi import FastAPI, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from expert_service.api import projects, pipeline, data, chat, meta_chat
from expert_service.db.connection import get_session
from expert_service.db.models import Assessment, Entry, Project, Source
from expert_service.chat.meta_agent import invalidate_meta_cache
from expert_service.rms import api as rms_api

app = FastAPI(title="Expert Service", version="0.1.0")

# API routes
app.include_router(projects.router)
app.include_router(pipeline.router)
app.include_router(data.router)
app.include_router(chat.router)
app.include_router(meta_chat.router)

# Templates
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# --- Web UI Routes ---


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: AsyncSession = Depends(get_session)):
    """Projects list page."""
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    project_list = result.scalars().all()

    # Get counts for each project
    projects_with_stats = []
    for p in project_list:
        source_count = await session.scalar(
            select(func.count()).select_from(Source).where(Source.project_id == p.id)
        )
        entry_count = await session.scalar(
            select(func.count()).select_from(Entry).where(Entry.project_id == p.id)
        )
        belief_count = await session.scalar(
            sa_text("SELECT count(*) FROM rms_nodes WHERE project_id = :pid AND truth_value = 'IN'"),
            {"pid": str(p.id)},
        )
        projects_with_stats.append({
            "id": p.id,
            "name": p.name,
            "domain": p.domain,
            "source_count": source_count or 0,
            "entry_count": entry_count or 0,
            "belief_count": belief_count or 0,
        })

    return templates.TemplateResponse(request, "projects/list.html", {
        "projects": projects_with_stats,
    })


@app.get("/meta/chat", response_class=HTMLResponse)
async def meta_chat_page(request: Request, session: AsyncSession = Depends(get_session)):
    """Meta-expert chat page — routes questions across all domain experts."""
    result = await session.execute(select(Project).order_by(Project.name))
    project_list = result.scalars().all()
    experts = [
        {"name": p.name, "domain": p.domain, "id": str(p.id)}
        for p in project_list
        if p.name != "meta-expert"
    ]
    return templates.TemplateResponse(request, "chat/meta_chat.html", {
        "experts": experts,
    })


@app.get("/projects/new", response_class=HTMLResponse)
async def new_project_form(request: Request):
    return templates.TemplateResponse(request, "projects/create.html")


@app.post("/projects/new")
async def create_project_form(
    request: Request,
    name: str = Form(...),
    domain: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    project = Project(name=name, domain=domain)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    invalidate_meta_cache()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(
    request: Request,
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)

    stats = {
        "sources": await session.scalar(
            select(func.count()).select_from(Source).where(Source.project_id == project_id)
        ) or 0,
        "entries": await session.scalar(
            select(func.count()).select_from(Entry).where(Entry.project_id == project_id)
        ) or 0,
        "beliefs": await session.scalar(
            sa_text("SELECT count(*) FROM rms_nodes WHERE project_id = :pid AND truth_value = 'IN'"),
            {"pid": str(project_id)},
        ) or 0,
        "nogoods": await session.scalar(
            sa_text("SELECT count(*) FROM rms_nogoods WHERE project_id = :pid"),
            {"pid": str(project_id)},
        ) or 0,
        "assessments": await session.scalar(
            select(func.count()).select_from(Assessment).where(Assessment.project_id == project_id)
        ) or 0,
    }

    entry_result = await session.execute(
        select(Entry.id, Entry.topic, Entry.title, Entry.created_at)
        .where(Entry.project_id == project_id)
        .order_by(Entry.created_at.desc())
        .limit(10)
    )
    entries = [dict(r._mapping) for r in entry_result.all()]
    for e in entries:
        e["created_at"] = e["created_at"].isoformat() if e["created_at"] else ""

    return templates.TemplateResponse(request, "projects/detail.html", {
        "project": {"id": project_id, "name": project.name, "domain": project.domain},
        "stats": stats,
        "entries": entries,
    })


@app.get("/projects/{project_id}/chat", response_class=HTMLResponse)
async def chat_page(request: Request, project_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)
    # Redirect meta-expert project chat to the dedicated meta-expert UI
    if project.name == "meta-expert":
        return RedirectResponse("/meta/chat", status_code=303)
    return templates.TemplateResponse(request, "chat/chat.html", {
        "project": {"id": project_id, "name": project.name, "domain": project.domain},
    })


@app.get("/projects/{project_id}/ingest", response_class=HTMLResponse)
async def ingest_form(request: Request, project_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)
    return templates.TemplateResponse(request, "ingest/form.html", {
        "project": {"id": project_id, "name": project.name},
    })


@app.get("/projects/{project_id}/beliefs/review", response_class=HTMLResponse)
async def beliefs_review_page(
    request: Request,
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)

    # Get OUT nodes (proposed but not yet accepted)
    out_result = await asyncio.to_thread(rms_api.list_nodes, project_id, status="OUT")
    beliefs = out_result["nodes"]

    return templates.TemplateResponse(request, "beliefs/review.html", {
        "project": {"id": project_id, "name": project.name},
        "beliefs": [{"id": b["id"], "text": b["text"], "source": ""} for b in beliefs],
    })


@app.post("/projects/{project_id}/beliefs/review")
async def beliefs_review_submit(
    request: Request,
    project_id: UUID,
):
    """Handle form submission of belief review decisions."""
    form_data = await request.form()

    # Extract decisions from form fields (decision_belief-id = accept|reject|pending)
    decisions = {}
    for key, value in form_data.items():
        if key.startswith("decision_") and value in ("accept", "reject"):
            belief_id = key[len("decision_"):]
            decisions[belief_id] = value

    if not decisions:
        return RedirectResponse(
            f"/projects/{project_id}/beliefs/review", status_code=303
        )

    # Update RMS nodes via assert/retract
    def _apply_decisions():
        for belief_id, decision in decisions.items():
            try:
                if decision == "accept":
                    rms_api.assert_node(project_id, belief_id)
                # "reject" leaves node as OUT (already retracted during proposal)
            except KeyError:
                pass

    await asyncio.to_thread(_apply_decisions)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


def main():
    """Entry point for the expert-service command."""
    uvicorn.run("expert_service.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()

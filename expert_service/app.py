"""FastAPI application — API + web UI for expert-service."""

from pathlib import Path
from uuid import UUID

import uvicorn
from fastapi import FastAPI, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from expert_service.api import projects, pipeline, data
from expert_service.db.connection import get_session
from expert_service.db.models import Assessment, Claim, Entry, Nogood, Project, Source

app = FastAPI(title="Expert Service", version="0.1.0")

# API routes
app.include_router(projects.router)
app.include_router(pipeline.router)
app.include_router(data.router)

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
        claim_count = await session.scalar(
            select(func.count()).select_from(Claim).where(
                Claim.project_id == p.id, Claim.status == "IN"
            )
        )
        projects_with_stats.append({
            "id": p.id,
            "name": p.name,
            "domain": p.domain,
            "source_count": source_count or 0,
            "entry_count": entry_count or 0,
            "claim_count": claim_count or 0,
        })

    return templates.TemplateResponse("projects/list.html", {
        "request": request,
        "projects": projects_with_stats,
    })


@app.get("/projects/new", response_class=HTMLResponse)
async def new_project_form(request: Request):
    return templates.TemplateResponse("projects/create.html", {"request": request})


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
        "claims": await session.scalar(
            select(func.count()).select_from(Claim).where(
                Claim.project_id == project_id, Claim.status == "IN"
            )
        ) or 0,
        "nogoods": await session.scalar(
            select(func.count()).select_from(Nogood).where(Nogood.project_id == project_id)
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

    return templates.TemplateResponse("projects/detail.html", {
        "request": request,
        "project": {"id": project_id, "name": project.name, "domain": project.domain},
        "stats": stats,
        "entries": entries,
    })


@app.get("/projects/{project_id}/ingest", response_class=HTMLResponse)
async def ingest_form(request: Request, project_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)
    return templates.TemplateResponse("ingest/form.html", {
        "request": request,
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

    claim_result = await session.execute(
        select(Claim).where(
            Claim.project_id == project_id,
            Claim.status == "PROPOSED",
            Claim.review_status == "pending",
        )
    )
    beliefs = claim_result.scalars().all()

    return templates.TemplateResponse("beliefs/review.html", {
        "request": request,
        "project": {"id": project_id, "name": project.name},
        "beliefs": [{"id": b.id, "text": b.text, "source": b.source} for b in beliefs],
    })


@app.post("/projects/{project_id}/beliefs/review")
async def beliefs_review_submit(
    request: Request,
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
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

    # Update claims directly in DB (simpler than going through the graph for form submissions)
    for belief_id, decision in decisions.items():
        claim_result = await session.execute(
            select(Claim).where(
                Claim.id == belief_id,
                Claim.project_id == project_id,
            )
        )
        claim = claim_result.scalar_one_or_none()
        if claim:
            if decision == "accept":
                claim.status = "IN"
                claim.review_status = "accepted"
            elif decision == "reject":
                claim.status = "OUT"
                claim.review_status = "rejected"

    await session.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


def main():
    """Entry point for the expert-service command."""
    uvicorn.run("expert_service.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()

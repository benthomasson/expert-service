"""FastAPI application — API + web UI for expert-service."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import uvicorn
from fastapi import FastAPI, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from expert_service.api import projects, data, ask
from expert_service.auth import router as auth_router, verify_auth, verify_auth_web, _LoginRedirect
from expert_service.config import settings
from expert_service.db.connection import get_session, init_db
from expert_service.db.models import Assessment, Entry, Project, Source
from expert_service.rbac import UserInfo
from expert_service.rms import api as rms_api

# LLM-dependent modules — only imported when LLM mode is enabled.
# In no-LLM mode, clients bring their own LLM and use the data endpoints directly.
if settings.llm_enabled:
    from expert_service.api import pipeline, chat, meta_chat
    from expert_service.chat.meta_agent import invalidate_meta_cache
else:
    def invalidate_meta_cache(): pass


@asynccontextmanager
async def lifespan(app):
    """Create SQLite tables on startup (no-op for PostgreSQL)."""
    init_db()
    yield

app = FastAPI(title="Expert Service", version="0.1.0", lifespan=lifespan)

# Session middleware for OAuth cookie sessions
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)


@app.middleware("http")
async def set_default_user(request: Request, call_next):
    """Ensure request.state.user always exists for templates."""
    request.state.user = None
    return await call_next(request)

# OAuth setup (optional — disabled when credentials not set)
oauth = None
if settings.google_client_id and settings.google_client_secret:
    if settings.secret_key == "dev-insecure-key":
        import warnings
        warnings.warn(
            "SECRET_KEY is set to the default insecure value. "
            "Set SECRET_KEY to a random string for production use.",
            stacklevel=1,
        )
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@app.exception_handler(_LoginRedirect)
async def login_redirect_handler(request: Request, exc: _LoginRedirect):
    return RedirectResponse(url="/login")


@app.get("/health")
async def health():
    return {"status": "ok", "llm": settings.llm_enabled}


# Auth routes (login/callback/logout — always public)
app.include_router(auth_router)

# API routes (protected by auth)
app.include_router(projects.router, dependencies=[Depends(verify_auth)])
app.include_router(data.router, dependencies=[Depends(verify_auth)])

if settings.llm_enabled:
    # LLM mode: chat.router provides /chat (streaming) and /ask (LLM-synthesized)
    app.include_router(chat.router, dependencies=[Depends(verify_auth)])
    app.include_router(meta_chat.router, dependencies=[Depends(verify_auth)])
    app.include_router(pipeline.router, dependencies=[Depends(verify_auth)])

# Always register: FTS-only /ask (shadowed by chat.router's /ask in LLM mode)
app.include_router(ask.router, dependencies=[Depends(verify_auth)])

# Templates
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["llm_enabled"] = settings.llm_enabled


# --- Web UI Routes ---


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, _user: UserInfo = Depends(verify_auth_web), session: AsyncSession = Depends(get_session)):
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
        belief_count = await asyncio.to_thread(rms_api.count_beliefs, p.id, "IN")
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


if settings.llm_enabled:
    @app.get("/meta/chat", response_class=HTMLResponse)
    async def meta_chat_page(request: Request, _user: UserInfo = Depends(verify_auth_web), session: AsyncSession = Depends(get_session)):
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
async def new_project_form(request: Request, _user: UserInfo = Depends(verify_auth_web)):
    return templates.TemplateResponse(request, "projects/create.html")


@app.post("/projects/new")
async def create_project_form(
    request: Request,
    name: str = Form(...),
    domain: str = Form(...),
    _user: UserInfo = Depends(verify_auth_web),
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
    _user: UserInfo = Depends(verify_auth_web),
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
        "beliefs": await asyncio.to_thread(rms_api.count_beliefs, project_id, "IN"),
        "nogoods": await asyncio.to_thread(rms_api.count_nogoods, project_id),
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


if settings.llm_enabled:
    @app.get("/projects/{project_id}/chat", response_class=HTMLResponse)
    async def chat_page(request: Request, project_id: UUID, _user: UserInfo = Depends(verify_auth_web), session: AsyncSession = Depends(get_session)):
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


@app.get("/projects/{project_id}/source/{path:path}", response_class=HTMLResponse)
async def source_view(
    request: Request,
    project_id: UUID,
    path: str,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    """Render a source document by its path (e.g. entries/2026/04/23/scan-ftl-reasons.md).

    Looks up the entry by matching the topic (filename stem) against entries in the project.
    """
    project = (await session.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)

    # Extract topic from path: "entries/2026/04/23/scan-ftl-reasons.md" → "scan-ftl-reasons"
    topic = Path(path).stem

    entry = (await session.execute(
        select(Entry).where(Entry.project_id == project_id, Entry.topic == topic).limit(1)
    )).scalar_one_or_none()
    if not entry:
        return HTMLResponse(f"Source not found: {path}", status_code=404)

    return templates.TemplateResponse(request, "entries/view.html", {
        "project": {"id": project_id, "name": project.name},
        "entry": {"id": entry.id, "title": entry.title, "topic": entry.topic},
        "content_json": json.dumps(entry.content),
    })


@app.get("/projects/{project_id}/entries/{entry_id}/view", response_class=HTMLResponse)
async def entry_view(
    request: Request,
    project_id: UUID,
    entry_id: str,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    """Render an entry's markdown content in a simple viewer."""
    project = (await session.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)

    entry = (await session.execute(
        select(Entry).where(Entry.project_id == project_id, Entry.id == entry_id)
    )).scalar_one_or_none()
    if not entry:
        return HTMLResponse("Entry not found", status_code=404)

    return templates.TemplateResponse(request, "entries/view.html", {
        "project": {"id": project_id, "name": project.name},
        "entry": {"id": entry.id, "title": entry.title, "topic": entry.topic},
        "content_json": json.dumps(entry.content),
    })


@app.get("/projects/{project_id}/entries/{entry_id}/report", response_class=HTMLResponse)
async def entry_report(
    request: Request,
    project_id: UUID,
    entry_id: str,
    _user: UserInfo = Depends(verify_auth_web),
    session: AsyncSession = Depends(get_session),
):
    """Render an entry as an interactive report with Explain/What-if buttons on belief references."""
    project = (await session.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        return HTMLResponse("Project not found", status_code=404)

    entry = (await session.execute(
        select(Entry).where(Entry.project_id == project_id, Entry.id == entry_id)
    )).scalar_one_or_none()
    if not entry:
        return HTMLResponse("Entry not found", status_code=404)

    return templates.TemplateResponse(request, "reports/view.html", {
        "project": {"id": project_id, "name": project.name},
        "entry": {"id": entry.id, "title": entry.title, "topic": entry.topic},
        "content_json": json.dumps(entry.content),
    })


if settings.llm_enabled:
    @app.get("/projects/{project_id}/ingest", response_class=HTMLResponse)
    async def ingest_form(request: Request, project_id: UUID, _user: UserInfo = Depends(verify_auth_web), session: AsyncSession = Depends(get_session)):
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
    _user: UserInfo = Depends(verify_auth_web),
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
    _user: UserInfo = Depends(verify_auth_web),
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

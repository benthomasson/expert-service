# Checkpoint

**Saved:** 2026-03-19 15:30
**Project:** /Users/ben/git/expert-service

## Task

Added a meta-expert agent that routes questions across all domain experts, with its own RMS to learn about expert capabilities.

## Status

- [x] Renamed `_get_checkpointer` → `get_checkpointer` in `chat/agent.py`
- [x] Created `chat/meta_tools.py` — `list_experts` and `ask_expert` tools
- [x] Created `chat/meta_agent.py` — agent factory with auto-created project, dynamic system prompt
- [x] Created `chat/meta_loop.py` — SSE streaming for meta-expert
- [x] Created `api/meta_chat.py` — `POST /api/meta/chat` endpoint
- [x] Created `templates/chat/meta_chat.html` — meta-expert chat UI
- [x] Registered routes in `app.py`, added nav link in `base.html`, added card in `list.html`
- [x] Added cache invalidation in `projects.py` and `app.py` on project create/delete
- [ ] Not yet tested — needs `docker compose up -d --build service`

## Key Files

- `expert_service/chat/meta_tools.py` — `make_meta_tools(experts_map, model)` with `list_experts` (sync) and `ask_expert` (async, invokes sub-agent)
- `expert_service/chat/meta_agent.py` — `get_meta_agent(model)`, `_ensure_meta_project()`, dynamic system prompt, `invalidate_meta_cache()`
- `expert_service/chat/meta_loop.py` — `meta_chat_stream(model, message, thread_id)` mirrors loop.py
- `expert_service/api/meta_chat.py` — `POST /api/meta/chat` SSE endpoint
- `expert_service/templates/chat/meta_chat.html` — meta-expert chat UI with cross-project citation verification
- `expert_service/chat/agent.py` — renamed `get_checkpointer()` (was private)
- `expert_service/api/projects.py` — added `invalidate_meta_cache()` on create/delete
- `expert_service/app.py` — registered meta_chat.router, added `/meta/chat` web route

## Commands

```bash
# Rebuild and test
source ~/git/expert-service/.env && cd ~/git/expert-service && docker compose up -d --build service

# Check meta-expert project was created
docker compose exec postgres psql -U expert -d expert_service -c "SELECT id, name, domain FROM projects WHERE name = 'meta-expert';"
```

## Next Step

Build and test the meta-expert. Navigate to `/meta/chat` and ask a question that should route to one of the domain experts.

## Context

- The meta-expert is a regular project (auto-created on first agent access) with domain "Expert routing and cross-domain knowledge synthesis"
- It gets all 19 standard tools (search, RMS, entries, etc.) scoped to its own project PLUS 2 meta tools
- `ask_expert` is async — uses `agent.ainvoke()` with ephemeral threads to get complete answers from sub-agents
- The meta-expert's system prompt dynamically lists available experts
- Cache invalidation clears `_meta_agents` dict when projects are created/deleted
- `GOOGLE_CLOUD_PROJECT=redhat-ai-analysis` must be set (source .env) before docker compose up

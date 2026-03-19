# Checkpoint

**Saved:** 2026-03-19
**Project:** /Users/ben/git/expert-service

## Task

Replace the claims/nogoods system in expert-service with RMS (Reason Maintenance System) backed by PostgreSQL.

## Status

All implementation steps complete. Not yet tested or committed.

- [x] Add `rms` dependency to pyproject.toml
- [x] Add 4 PostgreSQL RMS tables to schema.sql
- [x] Create PgStorage adapter (`expert_service/rms/pg_storage.py`)
- [x] Create project-scoped RMS API (`expert_service/rms/api.py`)
- [x] Add 12 RMS tools to `chat/tools.py`
- [x] Update beliefs graph, assessment graph, data API, projects API, pipeline API, app.py, embeddings.py, templates
- [x] Update import script
- [ ] Test the integration
- [ ] Commit changes

## Key Files

- `expert_service/rms/pg_storage.py` — PostgreSQL storage adapter for RMS Network
- `expert_service/rms/api.py` — project-scoped API with `_with_network()` context manager
- `expert_service/chat/tools.py` — 12 new RMS tools + updated existing belief tools
- `expert_service/db/schema.sql` — 4 new tables: rms_nodes, rms_justifications, rms_nogoods, rms_propagation_log

## Next Step

Test: `cd ~/git/expert-service && docker compose down -v && docker compose up -d --build`, then import an expert repo.

## Context

- PgStorage uses clear-and-rewrite strategy (same as rms_lib SQLite Storage)
- `asyncio.to_thread()` bridges sync RMS API from async FastAPI
- All Claim/Nogood model imports removed from active code

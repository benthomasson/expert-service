# Checkpoint

**Saved:** 2026-03-05 17:30
**Project:** /Users/ben/git/expert-service

## Task

Building expert-service — LangGraph-based web service. All 4 pipeline phases complete. Chat interface with tool-calling, semantic search, prompt caching, and markdown rendering all working.

## Status

- [x] Phase 1-4: Foundation, Ingest, Beliefs, Assessment — all complete
- [x] Docker Compose working — pgvector/pgvector:pg16 + service
- [x] Import script — imported aap-expert: 111 sources, 112 entries, 237 beliefs
- [x] Chat interface with 8 tools: search_knowledge, read_entry, list_entries, list_beliefs, read_source, grep_content, semantic_search
- [x] Semantic search via pgvector + fastembed (BAAI/bge-small-en-v1.5, 384 dimensions)
- [x] Embeddings built: 112 entries, 111 sources, 237 claims (460 vectors)
- [x] Prompt caching — Claude: cache_control ephemeral on SystemMessage; Gemini: create_context_cache with 1hr TTL (graceful fallback if content too small)
- [x] Markdown rendering in chat UI via marked.js
- [x] System prompt tuned to prevent redundant tool calls

## Key Files

- `expert_service/chat/tools.py` — 8 tools including semantic_search. Factory `make_tools(project_id)` scopes tools via closures.
- `expert_service/chat/loop.py` — Async streaming tool-calling loop. Buffered streaming, Gemini context cache management.
- `expert_service/api/chat.py` — POST /api/projects/{id}/chat. System prompt with cache_control for Claude.
- `expert_service/embeddings.py` — fastembed batch embedding + pgvector storage. `build_embeddings(project_id)` and `embed_query(query)`.
- `expert_service/llm/provider.py` — ChatVertexAI for Gemini (with optional cached_content), ChatAnthropicVertex for Claude.
- `expert_service/templates/chat/chat.html` — Chat UI with marked.js markdown rendering, model selector.
- `expert_service/db/schema.sql` — Includes pgvector extension + embeddings table with vector(384).
- `expert_service/db/models.py` — Embedding model with pgvector Vector(384) column.
- `scripts/build_embeddings.py` — CLI to build embeddings per project.
- `scripts/import_expert.py` — Imports entries, sources, beliefs from file-based expert repos.

## Commands

```bash
cd ~/git/expert-service

# Build and start
docker compose up -d --build service

# Full rebuild (destroys data — need reimport)
docker compose down -v && docker compose up -d --build

# Import an expert
uv run python scripts/import_expert.py ~/git/aap-expert --name aap-expert --domain "Ansible Automation Platform 2.6"

# Build embeddings (note port 5433 for local access)
DATABASE_URL_SYNC="postgresql+psycopg://expert:expert_dev@localhost:5433/expert_service" \
  uv run python scripts/build_embeddings.py --project-id <project-id>

# Test chat
curl -s -N -X POST http://localhost:8000/api/projects/<project-id>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is EDA?", "model": "gemini-2.5-pro", "thread_id": "test1"}'

# AAP project ID: d734bae1-7356-476d-82ce-2af09e76c1a6
```

## Next Step

Consider adding conversation context management (sliding window or message trimming) to prevent hitting context window limits on long conversations. Also consider pgvector IVFFlat index (currently skipped in schema — could add after sufficient rows exist).

## Context

- **pgvector image**: Using `pgvector/pgvector:pg16` instead of `postgres:16`. Switching requires `docker compose down -v` (destroys data).
- **Gemini context caching minimum**: Requires ~32K tokens. System prompt is ~150 tokens, so cache creation silently fails and falls back to no caching. Mechanism is in place for when conversations grow large enough.
- **Claude prompt caching**: Works immediately via `cache_control: {"type": "ephemeral"}` on SystemMessage. No minimum size.
- **Semantic search SQL**: Uses `CAST(:qvec AS vector)` instead of `::vector` to avoid SQLAlchemy parameter binding conflict with `::`.
- **marked.js**: CDN-loaded in extra_head block. Raw markdown accumulated during streaming, rendered to HTML on stream completion.
- **Three search channels**: search_knowledge (FTS), grep_content (ILIKE), semantic_search (pgvector cosine). System prompt instructs LLM to pick ONE.

# Checkpoint

**Saved:** 2026-03-25 11:45
**Project:** /Users/ben/git/expert-service

## Task

Migrated expert-service from `rms` to `ftl-reasons`, fixed Jinja2 template errors, fixed garbled multi-expert streaming, and added citation guard to reflection prompt to prevent bad beliefs.

## Status

- [x] Migrated `rms` → `ftl-reasons` (1 dependency + 5 import changes)
- [x] Fixed Starlette `TemplateResponse` API (7 calls updated to new convention)
- [x] Fixed Colima disk space (removed 50GB langfuse volumes, installed qemu)
- [x] Fixed garbled multi-expert streaming (`awaiting_tools` flag in `meta_loop.py`)
- [x] Fixed reflection prompt — only record cited positive knowledge
- [x] Retracted bad beliefs: `openshift-expert-lacks-aap-install-docs`, `rhel-expert-knows-firewalld-management`, `rhel-expert-knows-systemctl-commands`, `aap-expert-knows-ansible-firewalld-module`
- [x] Smoke tested: AAP install, AAP on OpenShift, firewall on RHEL, Ansible+firewall, Ansible+OpenShift
- [x] All commits pushed to github

## Key Files

- `expert_service/chat/meta_loop.py` — SSE streaming + reflection prompt. Two fixes: `awaiting_tools` flag prevents interleaved tokens; reflection prompt requires cited sources before recording beliefs
- `expert_service/rms/api.py` — `rms_lib` → `reasons_lib` (3 imports)
- `expert_service/rms/pg_storage.py` — `rms_lib` → `reasons_lib` (2 imports)
- `expert_service/app.py` — `TemplateResponse(request, "name.html", {})` new API (7 calls)
- `pyproject.toml` — `ftl-reasons` replaces `rms @ git+...`
- `expert_service/config.py` — DB defaults on port 5432, Docker exposes on 5433

## Commands

```bash
# Run RMS operations against Docker PG from host
DATABASE_URL_SYNC="postgresql+psycopg://expert:expert_dev@localhost:5433/expert_service" uv run python3 -c "
from expert_service.rms.api import search, retract_node
from uuid import UUID
pid = UUID('b3ba781a-7a17-459a-9436-6531a35774bc')  # meta-expert
search(pid, 'knows')
"

# Rebuild and start
docker compose up -d --build

# Check Colima disk
colima ssh -- df -h /
```

## Next Step

Continue exercising expert-service with ftl-reasons this week (days 2-5 of migration plan). Test retraction cascades, nogood detection, and cross-expert contradictions. Consider adding a programmatic citation check in the reflection step (not just prompt-based) for stronger enforcement.

## Context

- **ftl-reasons 0.3.0** installed, `rms 0.1.0` removed. Same API, `reasons_lib` instead of `rms_lib`.
- **Colima disk**: Was 96G/96G full. Removed langfuse volumes (50GB). Now ~48GB free. Installed qemu via brew but Colima uses VZ driver so disk resize didn't work — just freed space instead.
- **Reflection prompt evolution**: v1 recorded everything → v2 blocked negative/transient → v3 requires cited sources. v3 is working: uncited answers (firewall on RHEL) correctly skipped, cited answers (OpenShift RHCOS) correctly recorded.
- **Two-layer insight confirmed**: LLM general knowledge fills gaps (correct firewall answer without citations), but only expert knowledge base citations get tracked as beliefs. This is the probabilistic+exact architecture working.
- **Project IDs**: meta-expert=`b3ba781a`, aap-expert=`a037a6a3`, rhel-expert=`6e82621f`, openshift-expert=`23c26c17`
- **Latest commit**: `4fb30eb` — Fix garbled multi-expert streaming and prevent uncited belief recording

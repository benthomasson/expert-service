# Checkpoint

**Saved:** 2026-03-25 12:30
**Project:** /Users/ben/git/expert-service

## Task

Building meta-expert evaluation framework for expert-service. Phase 1 (routing accuracy) complete and smoke-tested. Migrated from rms to ftl-reasons earlier this session.

## Status

### Completed this session
- [x] Migrated `rms` → `ftl-reasons` (1 dependency + 5 import changes)
- [x] Fixed Starlette `TemplateResponse` API (7 calls)
- [x] Fixed Colima disk space (removed 50GB langfuse volumes)
- [x] Fixed garbled multi-expert streaming (`awaiting_tools` flag)
- [x] Fixed reflection prompt — v3 requires cited sources before recording beliefs
- [x] Retracted bad beliefs from transient errors and uncited answers
- [x] Smoke tested 7 meta-expert queries across 3 experts
- [x] Built Phase 1 meta-expert eval: driver, scorer, 45 questions, CLI runner
- [x] Smoke-tested eval: single-domain 100% F1, cross-domain 83% F1, out-of-scope 100% F1
- [x] All commits pushed

### Not yet started
- [ ] Run full 45-question routing eval
- [ ] Phase 2: Synthesis quality (CIAK scoring)
- [ ] Phase 3: Citation preservation scoring
- [ ] Programmatic citation check in reflection step (not just prompt-based)

## Key Files

- `eval/meta_systems.py` — `MetaExpertDriver` captures ask_expert calls, reflection events, citations from SSE
- `eval/meta_scoring.py` — `score_routing()` precision/recall/F1, `score_citations()`, `aggregate_routing_scores()`
- `eval/meta_questions.json` — 45 questions: 30 single-domain, 10 cross-domain, 5 out-of-scope
- `eval/run_meta_eval.py` — CLI runner with `--category`, `--limit`, `--model`, `--output`
- `expert_service/chat/meta_loop.py` — streaming fix + reflection prompt v3
- `expert_service/chat/meta_agent.py` — meta-expert agent factory, system prompt
- `expert_service/chat/meta_tools.py` — `ask_expert` and `list_experts` tools

## Commands

```bash
# Run full meta-expert routing eval
uv run python3 -m eval.run_meta_eval

# Run by category
uv run python3 -m eval.run_meta_eval --category single --limit 5
uv run python3 -m eval.run_meta_eval --category cross
uv run python3 -m eval.run_meta_eval --category out-of-scope

# RMS operations against Docker PG
DATABASE_URL_SYNC="postgresql+psycopg://expert:expert_dev@localhost:5433/expert_service" uv run python3 -c "
from expert_service.rms.api import search
from uuid import UUID
pid = UUID('b3ba781a-7a17-459a-9436-6531a35774bc')  # meta-expert
print(search(pid, 'knows'))
"

# Rebuild service
docker compose up -d --build
```

## Next Step

Run the full 45-question routing eval (`uv run python3 -m eval.run_meta_eval`) to establish a baseline, then start Phase 2 (synthesis quality with CIAK scoring) for the 10 cross-domain questions.

## Context

- **ftl-reasons 0.3.0** installed, `rms 0.1.0` removed
- **Colima disk**: ~48GB free after removing langfuse volumes
- **Reflection prompt v3**: Only records beliefs when expert cited specific belief IDs, entry IDs, or sources. Tested working — uncited answers skipped, cited answers recorded.
- **Routing eval smoke test results**: R32 ("deploy AAP on OpenShift") got P=1.0 R=0.5 F1=0.67 — meta-expert only asked aap-expert, missed openshift-expert. Arguably reasonable but eval correctly flags it.
- **Project IDs**: meta-expert=`b3ba781a`, aap-expert=`a037a6a3`, rhel-expert=`6e82621f`, openshift-expert=`23c26c17`
- **Eval plan**: 6-phase plan in `~/git/project-analyze-understanding/entries/2026/03/20/meta-expert-evaluation-plan.md`
- **Latest commit**: `8b23a03` — Add meta-expert routing evaluation framework

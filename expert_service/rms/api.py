"""Project-scoped RMS API for expert-service.

PostgreSQL: delegates to reasons_lib.pg.PgApi for row-level operations.
SQLite: delegates to reasons_lib.api functions with per-project db files.
"""

from pathlib import Path
from uuid import UUID

from expert_service.config import settings


def _is_sqlite() -> bool:
    return settings.db_backend == "sqlite"


# --- PostgreSQL helpers ---

def _conninfo() -> str:
    """Convert SQLAlchemy sync URL to psycopg conninfo."""
    url = settings.database_url_sync
    if "+psycopg" in url:
        url = url.replace("+psycopg", "")
    return url


def _api(project_id: UUID):
    """Create a PgApi instance for a project."""
    from reasons_lib.pg import PgApi
    return PgApi(_conninfo(), project_id)


# --- SQLite helpers ---

def _db_path(project_id: UUID) -> str:
    """Per-project SQLite database path for reasons_lib.Storage."""
    path = settings.data_dir / str(project_id)
    path.mkdir(parents=True, exist_ok=True)
    return str(path / "reasons.db")


# --- Public API (dispatch based on backend) ---

def add_node(
    project_id: UUID,
    node_id: str,
    text: str,
    sl: str = "",
    cp: str = "",
    unless: str = "",
    label: str = "",
    source: str = "",
) -> dict:
    """Add a node to the project's RMS network."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.add_node(node_id, text, sl=sl, cp=cp, unless=unless,
                             label=label, source=source, db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.add_node(node_id, text, sl=sl, cp=cp, unless=unless,
                            label=label, source=source)


def retract_node(project_id: UUID, node_id: str) -> dict:
    """Retract a node and cascade."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.retract_node(node_id, db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.retract_node(node_id)


def assert_node(project_id: UUID, node_id: str) -> dict:
    """Assert a node and cascade restoration."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.assert_node(node_id, db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.assert_node(node_id)


def get_status(project_id: UUID) -> dict:
    """Get all nodes with truth values."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.get_status(db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.get_status()


def show_node(project_id: UUID, node_id: str) -> dict:
    """Get full details for a node."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.show_node(node_id, db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.show_node(node_id)


def explain_node(project_id: UUID, node_id: str) -> dict:
    """Explain why a node is IN or OUT."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.explain_node(node_id, db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.explain_node(node_id)


def trace_assumptions(project_id: UUID, node_id: str) -> dict:
    """Trace backward to find all premises a node rests on."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.trace_assumptions(node_id, db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.trace_assumptions(node_id)


def challenge(
    project_id: UUID,
    target_id: str,
    reason: str,
    challenge_id: str | None = None,
) -> dict:
    """Challenge a node -- target goes OUT."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.challenge(target_id, reason, challenge_id=challenge_id,
                              db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.challenge(target_id, reason, challenge_id=challenge_id)


def defend(
    project_id: UUID,
    target_id: str,
    challenge_id: str,
    reason: str,
    defense_id: str | None = None,
) -> dict:
    """Defend a node against a challenge -- target restored."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.defend(target_id, challenge_id, reason,
                           defense_id=defense_id, db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.defend(target_id, challenge_id, reason, defense_id=defense_id)


def add_nogood(project_id: UUID, node_ids: list[str]) -> dict:
    """Record a contradiction and use backtracking to resolve."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.add_nogood(node_ids, db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.add_nogood(node_ids)


def search(project_id: UUID, query: str) -> dict:
    """Search nodes by text using full-text search."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        result = rlib.search(query, db_path=_db_path(project_id), format="dict")
        # reasons_lib.api.search returns str for non-dict formats
        if isinstance(result, dict):
            return {"results": result.get("results", []), "count": result.get("count", 0)}
        return {"results": [], "count": 0}
    with _api(project_id) as api:
        result = api.search(query, format="dict")
    return {"results": result["results"], "count": result["count"]}


def list_nodes(
    project_id: UUID,
    status: str | None = None,
    premises_only: bool = False,
) -> dict:
    """List nodes with optional filters."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.list_nodes(status=status, premises_only=premises_only,
                               db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.list_nodes(status=status, premises_only=premises_only)


def compact(project_id: UUID, budget: int = 500) -> str:
    """Generate a token-budgeted summary of the belief network."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.compact(budget=budget, db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.compact(budget=budget)


def list_gated(project_id: UUID) -> dict:
    """Find OUT beliefs blocked by IN outlist nodes (active gates)."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.list_gated(db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.list_gated()


def what_if_retract(project_id: UUID, node_id: str) -> dict:
    """Simulate retracting a node — shows cascade without modifying the database."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.what_if_retract(node_id, db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.what_if_retract(node_id)


def what_if_assert(project_id: UUID, node_id: str) -> dict:
    """Simulate asserting a node — shows cascade without modifying the database."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        return rlib.what_if_assert(node_id, db_path=_db_path(project_id))
    with _api(project_id) as api:
        return api.what_if_assert(node_id)


# --- Belief/nogood count helpers (avoids direct rms_nodes SQL) ---

def count_beliefs(project_id: UUID, status: str | None = "IN") -> int:
    """Count beliefs, optionally filtered by truth_value."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        result = rlib.get_status(db_path=_db_path(project_id))
        if status:
            return sum(1 for n in result.get("nodes", []) if n.get("truth_value") == status)
        return len(result.get("nodes", []))
    from expert_service.db.connection import get_sync_session
    from sqlalchemy import text
    with get_sync_session() as session:
        if status:
            return session.execute(
                text("SELECT count(*) FROM rms_nodes WHERE project_id = :pid AND truth_value = :st"),
                {"pid": str(project_id), "st": status},
            ).scalar() or 0
        return session.execute(
            text("SELECT count(*) FROM rms_nodes WHERE project_id = :pid"),
            {"pid": str(project_id)},
        ).scalar() or 0


def count_nogoods(project_id: UUID) -> int:
    """Count nogood records for a project."""
    if _is_sqlite():
        import reasons_lib.api as rlib
        result = rlib.get_status(db_path=_db_path(project_id))
        return len(result.get("nogoods", []))
    from expert_service.db.connection import get_sync_session
    from sqlalchemy import text
    with get_sync_session() as session:
        return session.execute(
            text("SELECT count(*) FROM rms_nogoods WHERE project_id = :pid"),
            {"pid": str(project_id)},
        ).scalar() or 0


def search_beliefs_fts(project_id: UUID, query: str, limit: int = 10) -> list[dict]:
    """Search IN beliefs by text. Returns list of dicts with id, text, truth_value, source, source_url."""
    if _is_sqlite():
        result = search(project_id, query)
        rows = result.get("results", [])[:limit]
        # Ensure all fields present
        for r in rows:
            r.setdefault("source", "")
            r.setdefault("source_url", "")
            r.setdefault("truth_value", "IN")
        return rows
    # PostgreSQL: use existing tsvector search
    from expert_service.db.connection import get_sync_session
    from expert_service.db.search import fts_clause
    from sqlalchemy import text
    where, order, params = fts_clause("text", query)
    params["pid"] = str(project_id)
    params["lim"] = limit
    order_clause = f"ORDER BY {order}" if order else ""
    with get_sync_session() as session:
        rows = session.execute(
            text(
                f"SELECT id, text, truth_value, source, source_url "
                f"FROM rms_nodes "
                f"WHERE project_id = :pid AND truth_value = 'IN' "
                f"AND {where} "
                f"{order_clause} "
                f"LIMIT :lim"
            ),
            params,
        ).all()
    return [
        {"id": r.id, "text": r.text, "truth_value": r.truth_value,
         "source": r.source or "", "source_url": r.source_url or ""}
        for r in rows
    ]


# Keywords that suggest a belief describes a problem, defect, or risk.
_NEGATIVE_TERMS = [
    'bug', 'defect', 'missing', 'fail', 'error', 'broken', 'incorrect',
    'wrong', 'risk', 'gap', 'lack', 'vulnerable', 'insecure', 'stale',
    'outdated', 'deprecated', 'fragile', 'brittle', 'hack', 'workaround',
    'technical debt', 'tech debt', 'not implemented', 'unimplemented',
    'incomplete', 'inconsistent', 'unclear', 'confusing', 'problem',
    'issue', 'concern', 'warning', 'danger', 'threat', 'weakness',
    'limitation', 'constraint', 'bottleneck', 'blocker', 'obstacle',
    'undermines', 'concentrated', 'single point of failure', 'no tests',
    'untested', 'not tested', 'hard-coded', 'hardcoded', 'tight coupling',
    'tightly coupled', 'monolithic', 'legacy', 'unmaintained',
    'worsening', 'decay', 'degradation', 'fragmentation', 'opacity',
    'ungoverned', 'unrecoverable', 'unverifiable', 'deadlock', 'paradox',
]


def list_negative_candidates(project_id: UUID) -> dict:
    """Find IN beliefs whose text matches negative-sentiment keywords.

    Returns candidates only — the chat agent classifies which are genuinely
    negative vs. beliefs that merely describe error-handling mechanisms.
    """
    if _is_sqlite():
        import reasons_lib.api as rlib
        status = rlib.get_status(db_path=_db_path(project_id))
        in_nodes = [n for n in status.get("nodes", []) if n.get("truth_value") == "IN"]
        total = len(in_nodes)
        candidates = []
        for n in in_nodes:
            text_lower = n["text"].lower()
            if any(term in text_lower for term in _NEGATIVE_TERMS):
                candidates.append({"id": n["id"], "text": n["text"]})
        candidates.sort(key=lambda c: c["id"])
        return {
            "candidates": candidates,
            "candidate_count": len(candidates),
            "total_in": total,
        }

    # PostgreSQL path
    from expert_service.db.connection import get_sync_session
    from sqlalchemy import text
    conditions = " OR ".join(
        f"lower(text) LIKE :t{i}" for i in range(len(_NEGATIVE_TERMS))
    )
    params = {f"t{i}": f"%{term}%" for i, term in enumerate(_NEGATIVE_TERMS)}
    params["pid"] = str(project_id)

    with get_sync_session() as session:
        total = session.execute(
            text(
                "SELECT count(*) FROM rms_nodes "
                "WHERE project_id = :pid AND truth_value = 'IN'"
            ),
            {"pid": params["pid"]},
        ).scalar()

        rows = session.execute(
            text(
                f"SELECT id, text FROM rms_nodes "
                f"WHERE project_id = :pid AND truth_value = 'IN' "
                f"AND ({conditions}) "
                f"ORDER BY id"
            ),
            params,
        ).all()

    return {
        "candidates": [{"id": r.id, "text": r.text} for r in rows],
        "candidate_count": len(rows),
        "total_in": total or 0,
    }

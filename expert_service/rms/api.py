"""Project-scoped RMS API for expert-service.

Delegates to reasons_lib.pg.PgApi for row-level PostgreSQL operations
instead of loading/saving the entire network per call.
"""

from uuid import UUID

from reasons_lib.pg import PgApi
from sqlalchemy import text

from expert_service.config import settings
from expert_service.db.connection import get_sync_session


def _conninfo() -> str:
    """Convert SQLAlchemy sync URL to psycopg conninfo."""
    url = settings.database_url_sync
    # Strip SQLAlchemy dialect prefix: postgresql+psycopg:// -> postgresql://
    if "+psycopg" in url:
        url = url.replace("+psycopg", "")
    return url


def _api(project_id: UUID) -> PgApi:
    """Create a PgApi instance for a project."""
    return PgApi(_conninfo(), project_id)


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
    with _api(project_id) as api:
        return api.add_node(node_id, text, sl=sl, cp=cp, unless=unless,
                            label=label, source=source)


def retract_node(project_id: UUID, node_id: str) -> dict:
    """Retract a node and cascade."""
    with _api(project_id) as api:
        return api.retract_node(node_id)


def assert_node(project_id: UUID, node_id: str) -> dict:
    """Assert a node and cascade restoration."""
    with _api(project_id) as api:
        return api.assert_node(node_id)


def get_status(project_id: UUID) -> dict:
    """Get all nodes with truth values."""
    with _api(project_id) as api:
        return api.get_status()


def show_node(project_id: UUID, node_id: str) -> dict:
    """Get full details for a node."""
    with _api(project_id) as api:
        return api.show_node(node_id)


def explain_node(project_id: UUID, node_id: str) -> dict:
    """Explain why a node is IN or OUT."""
    with _api(project_id) as api:
        return api.explain_node(node_id)


def trace_assumptions(project_id: UUID, node_id: str) -> dict:
    """Trace backward to find all premises a node rests on."""
    with _api(project_id) as api:
        return api.trace_assumptions(node_id)


def challenge(
    project_id: UUID,
    target_id: str,
    reason: str,
    challenge_id: str | None = None,
) -> dict:
    """Challenge a node -- target goes OUT."""
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
    with _api(project_id) as api:
        return api.defend(target_id, challenge_id, reason, defense_id=defense_id)


def add_nogood(project_id: UUID, node_ids: list[str]) -> dict:
    """Record a contradiction and use backtracking to resolve."""
    with _api(project_id) as api:
        return api.add_nogood(node_ids)


def search(project_id: UUID, query: str) -> dict:
    """Search nodes by text using PostgreSQL full-text search (tsvector)."""
    with _api(project_id) as api:
        result = api.search(query, format="dict")
    return {"results": result["results"], "count": result["count"]}


def list_nodes(
    project_id: UUID,
    status: str | None = None,
    premises_only: bool = False,
) -> dict:
    """List nodes with optional filters."""
    with _api(project_id) as api:
        return api.list_nodes(status=status, premises_only=premises_only)


def compact(project_id: UUID, budget: int = 500) -> str:
    """Generate a token-budgeted summary of the belief network."""
    with _api(project_id) as api:
        return api.compact(budget=budget)


def list_gated(project_id: UUID) -> dict:
    """Find OUT beliefs blocked by IN outlist nodes (active gates)."""
    with _api(project_id) as api:
        return api.list_gated()


def what_if_retract(project_id: UUID, node_id: str) -> dict:
    """Simulate retracting a node — shows cascade without modifying the database."""
    with _api(project_id) as api:
        return api.what_if_retract(node_id)


def what_if_assert(project_id: UUID, node_id: str) -> dict:
    """Simulate asserting a node — shows cascade without modifying the database."""
    with _api(project_id) as api:
        return api.what_if_assert(node_id)


# Keywords that suggest a belief describes a problem, defect, or risk.
# Matches reasons_lib.api.NEGATIVE_TERMS.
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
    # Build SQL ILIKE OR chain
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

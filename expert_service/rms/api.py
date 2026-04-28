"""Project-scoped RMS API for expert-service.

Delegates to reasons_lib.pg.PgApi for row-level PostgreSQL operations
instead of loading/saving the entire network per call.
"""

from uuid import UUID

from reasons_lib.pg import PgApi

from expert_service.config import settings


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

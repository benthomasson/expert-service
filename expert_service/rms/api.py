"""Project-scoped RMS API for expert-service.

Same functions as rms_lib.api but using PostgreSQL storage and
project_id instead of db_path. Each function opens a sync session,
loads the network, operates, saves, and closes.
"""

import json
from uuid import UUID

from rms_lib import Justification
from rms_lib.network import Network

from expert_service.db.connection import get_sync_session
from .pg_storage import PgStorage


def _with_network(project_id: UUID, write: bool = False):
    """Context manager: load network from PG, operate, optionally save."""

    class _Ctx:
        def __init__(self):
            self.session = get_sync_session()
            self.storage = PgStorage(project_id, self.session)
            self.network = self.storage.load()

        def __enter__(self):
            return self.network

        def __exit__(self, exc_type, exc_val, exc_tb):
            if write and exc_type is None:
                self.storage.save(self.network)
            self.session.close()
            return False

    return _Ctx()


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
    outlist = [o.strip() for o in unless.split(",") if o.strip()] if unless else []
    justifications = []
    if sl:
        antecedents = [a.strip() for a in sl.split(",")]
        justifications.append(Justification(type="SL", antecedents=antecedents, outlist=outlist, label=label))
    elif cp:
        antecedents = [a.strip() for a in cp.split(",")]
        justifications.append(Justification(type="CP", antecedents=antecedents, outlist=outlist, label=label))
    elif outlist:
        justifications.append(Justification(type="SL", antecedents=[], outlist=outlist, label=label))

    with _with_network(project_id, write=True) as net:
        node = net.add_node(
            id=node_id,
            text=text,
            justifications=justifications or None,
            source=source,
        )
        jtype = justifications[0].type if justifications else "premise"
        return {"node_id": node_id, "truth_value": node.truth_value, "type": jtype}


def retract_node(project_id: UUID, node_id: str) -> dict:
    """Retract a node and cascade."""
    with _with_network(project_id, write=True) as net:
        changed = net.retract(node_id)
        return {"changed": changed}


def assert_node(project_id: UUID, node_id: str) -> dict:
    """Assert a node and cascade restoration."""
    with _with_network(project_id, write=True) as net:
        changed = net.assert_node(node_id)
        return {"changed": changed}


def get_status(project_id: UUID) -> dict:
    """Get all nodes with truth values."""
    with _with_network(project_id) as net:
        nodes = []
        for nid, node in sorted(net.nodes.items()):
            nodes.append({
                "id": nid,
                "text": node.text,
                "truth_value": node.truth_value,
                "justification_count": len(node.justifications),
            })
        in_count = sum(1 for n in nodes if n["truth_value"] == "IN")
        return {"nodes": nodes, "in_count": in_count, "total": len(nodes)}


def show_node(project_id: UUID, node_id: str) -> dict:
    """Get full details for a node."""
    with _with_network(project_id) as net:
        if node_id not in net.nodes:
            raise KeyError(f"Node '{node_id}' not found")
        node = net.nodes[node_id]
        return {
            "id": node.id,
            "text": node.text,
            "truth_value": node.truth_value,
            "source": node.source,
            "source_hash": node.source_hash,
            "justifications": [
                {"type": j.type, "antecedents": j.antecedents, "outlist": j.outlist, "label": j.label}
                for j in node.justifications
            ],
            "dependents": sorted(node.dependents),
            "metadata": node.metadata,
        }


def explain_node(project_id: UUID, node_id: str) -> dict:
    """Explain why a node is IN or OUT."""
    with _with_network(project_id) as net:
        steps = net.explain(node_id)
        return {"steps": steps}


def trace_assumptions(project_id: UUID, node_id: str) -> dict:
    """Trace backward to find all premises a node rests on."""
    with _with_network(project_id) as net:
        premises = net.trace_assumptions(node_id)
        return {"node_id": node_id, "premises": premises}


def challenge(
    project_id: UUID,
    target_id: str,
    reason: str,
    challenge_id: str | None = None,
) -> dict:
    """Challenge a node — target goes OUT."""
    with _with_network(project_id, write=True) as net:
        return net.challenge(target_id, reason, challenge_id=challenge_id)


def defend(
    project_id: UUID,
    target_id: str,
    challenge_id: str,
    reason: str,
    defense_id: str | None = None,
) -> dict:
    """Defend a node against a challenge — target restored."""
    with _with_network(project_id, write=True) as net:
        return net.defend(target_id, challenge_id, reason, defense_id=defense_id)


def add_nogood(project_id: UUID, node_ids: list[str]) -> dict:
    """Record a contradiction and use backtracking to resolve."""
    with _with_network(project_id, write=True) as net:
        all_in = all(
            nid in net.nodes and net.nodes[nid].truth_value == "IN"
            for nid in node_ids
        )
        culprits = net.find_culprits(node_ids) if all_in else []
        backtracked_to = culprits[0]["premise"] if culprits else None

        changed = net.add_nogood(node_ids)
        ng = net.nogoods[-1]
        return {
            "nogood_id": ng.id,
            "nodes": ng.nodes,
            "changed": changed,
            "backtracked_to": backtracked_to,
        }


def search(project_id: UUID, query: str) -> dict:
    """Search nodes by text or ID substring."""
    q = query.lower()
    with _with_network(project_id) as net:
        results = []
        for nid, node in sorted(net.nodes.items()):
            if q in nid.lower() or q in node.text.lower():
                results.append({
                    "id": nid,
                    "text": node.text,
                    "truth_value": node.truth_value,
                    "justification_count": len(node.justifications),
                    "dependent_count": len(node.dependents),
                })
        return {"results": results, "count": len(results)}


def list_nodes(
    project_id: UUID,
    status: str | None = None,
    premises_only: bool = False,
) -> dict:
    """List nodes with optional filters."""
    with _with_network(project_id) as net:
        nodes = []
        for nid, node in sorted(net.nodes.items()):
            if status and node.truth_value != status:
                continue
            if premises_only and node.justifications:
                continue
            nodes.append({
                "id": nid,
                "text": node.text,
                "truth_value": node.truth_value,
                "justification_count": len(node.justifications),
                "dependent_count": len(node.dependents),
            })
        return {"nodes": nodes, "count": len(nodes)}


def compact(project_id: UUID, budget: int = 500) -> str:
    """Generate a token-budgeted summary of the belief network."""
    from rms_lib.compact import compact as _compact

    with _with_network(project_id) as net:
        return _compact(net, budget=budget, truncate=True)

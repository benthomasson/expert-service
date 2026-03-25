"""PostgreSQL persistence for the RMS dependency network.

Drop-in replacement for rms_lib.storage.Storage that uses PostgreSQL
instead of SQLite, scoped by project_id for multi-tenant isolation.
"""

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session as SyncSession

from reasons_lib import Justification, Node, Nogood
from reasons_lib.network import Network


class PgStorage:
    """PostgreSQL persistence for an RMS Network, scoped by project_id."""

    def __init__(self, project_id: UUID, session: SyncSession):
        self.project_id = project_id
        self.session = session

    def load(self) -> Network:
        """Load a Network from PostgreSQL for this project."""
        network = Network()
        pid = str(self.project_id)

        # Load nodes
        node_rows = self.session.execute(
            text("SELECT id, text, truth_value, source, source_hash, date, metadata "
                 "FROM rms_nodes WHERE project_id = :pid"),
            {"pid": pid},
        ).fetchall()

        # Load justifications keyed by node_id
        just_rows = self.session.execute(
            text("SELECT node_id, type, antecedents, outlist, label "
                 "FROM rms_justifications WHERE project_id = :pid ORDER BY id"),
            {"pid": pid},
        ).fetchall()

        justifications_by_node: dict[str, list[Justification]] = {}
        for node_id, jtype, antecedents, outlist, label in just_rows:
            j = Justification(
                type=jtype,
                antecedents=antecedents if isinstance(antecedents, list) else json.loads(antecedents),
                outlist=outlist if isinstance(outlist, list) else json.loads(outlist),
                label=label or "",
            )
            justifications_by_node.setdefault(node_id, []).append(j)

        # Build nodes directly (bypass add_node to preserve exact state)
        for row in node_rows:
            nid, node_text, truth_value, source, source_hash, date, metadata = row
            meta = metadata if isinstance(metadata, dict) else json.loads(metadata or "{}")
            node = Node(
                id=nid,
                text=node_text,
                truth_value=truth_value,
                justifications=justifications_by_node.get(nid, []),
                source=source or "",
                source_hash=source_hash or "",
                date=date or "",
                metadata=meta,
            )
            network.nodes[nid] = node

        # Rebuild dependent index
        for node in network.nodes.values():
            for j in node.justifications:
                for ant_id in j.antecedents:
                    if ant_id in network.nodes:
                        network.nodes[ant_id].dependents.add(node.id)
                for out_id in j.outlist:
                    if out_id in network.nodes:
                        network.nodes[out_id].dependents.add(node.id)

        # Load nogoods
        ng_rows = self.session.execute(
            text("SELECT id, nodes, discovered, resolution "
                 "FROM rms_nogoods WHERE project_id = :pid"),
            {"pid": pid},
        ).fetchall()
        for ng_id, nodes, discovered, resolution in ng_rows:
            node_list = nodes if isinstance(nodes, list) else json.loads(nodes or "[]")
            network.nogoods.append(Nogood(
                id=ng_id,
                nodes=node_list,
                discovered=discovered or "",
                resolution=resolution or "",
            ))

        # Load log
        log_rows = self.session.execute(
            text("SELECT timestamp, action, target, value "
                 "FROM rms_propagation_log WHERE project_id = :pid ORDER BY id"),
            {"pid": pid},
        ).fetchall()
        for ts, action, target, value in log_rows:
            network.log.append({
                "timestamp": ts,
                "action": action,
                "target": target,
                "value": value,
            })

        return network

    def save(self, network: Network) -> None:
        """Persist the entire network state to PostgreSQL."""
        pid = str(self.project_id)

        # Clear existing data for this project
        self.session.execute(text("DELETE FROM rms_justifications WHERE project_id = :pid"), {"pid": pid})
        self.session.execute(text("DELETE FROM rms_propagation_log WHERE project_id = :pid"), {"pid": pid})
        self.session.execute(text("DELETE FROM rms_nogoods WHERE project_id = :pid"), {"pid": pid})
        self.session.execute(text("DELETE FROM rms_nodes WHERE project_id = :pid"), {"pid": pid})

        for node in network.nodes.values():
            self.session.execute(
                text("INSERT INTO rms_nodes (id, project_id, text, truth_value, source, source_hash, date, metadata) "
                     "VALUES (:id, :pid, :text, :tv, :source, :hash, :date, :meta)"),
                {
                    "id": node.id,
                    "pid": pid,
                    "text": node.text,
                    "tv": node.truth_value,
                    "source": node.source,
                    "hash": node.source_hash,
                    "date": node.date,
                    "meta": json.dumps(node.metadata),
                },
            )
            for j in node.justifications:
                self.session.execute(
                    text("INSERT INTO rms_justifications (node_id, project_id, type, antecedents, outlist, label) "
                         "VALUES (:nid, :pid, :type, :ant, :out, :label)"),
                    {
                        "nid": node.id,
                        "pid": pid,
                        "type": j.type,
                        "ant": json.dumps(j.antecedents),
                        "out": json.dumps(j.outlist),
                        "label": j.label,
                    },
                )

        for nogood in network.nogoods:
            self.session.execute(
                text("INSERT INTO rms_nogoods (id, project_id, nodes, discovered, resolution) "
                     "VALUES (:id, :pid, :nodes, :disc, :res)"),
                {
                    "id": nogood.id,
                    "pid": pid,
                    "nodes": json.dumps(nogood.nodes),
                    "disc": nogood.discovered,
                    "res": nogood.resolution,
                },
            )

        for entry in network.log:
            self.session.execute(
                text("INSERT INTO rms_propagation_log (project_id, timestamp, action, target, value) "
                     "VALUES (:pid, :ts, :action, :target, :value)"),
                {
                    "pid": pid,
                    "ts": entry["timestamp"],
                    "action": entry["action"],
                    "target": entry["target"],
                    "value": entry["value"],
                },
            )

        self.session.commit()

    def close(self) -> None:
        """Close the session (no-op — caller manages session lifecycle)."""
        pass

#!/usr/bin/env python3
"""Load a reasons.db (SQLite) into expert-service's PostgreSQL via bulk SQL.

Usage:
    python scripts/load_reasons_db.py <reasons.db path> <project_name> [--domain <domain>]

Examples:
    python scripts/load_reasons_db.py ~/git/redhat-expert/reasons.db redhat-expert --domain "Red Hat strategy"
    python scripts/load_reasons_db.py ~/git/agents-python-meta-expert/reasons.db meta-expert --domain "Cross-domain analysis"
"""

import json
import sqlite3
import sys

import psycopg


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    db_path = sys.argv[1]
    project_name = sys.argv[2]
    domain = "general"
    if "--domain" in sys.argv:
        domain = sys.argv[sys.argv.index("--domain") + 1]

    conninfo = "postgresql://ben@localhost:5432/expert_service"

    # Read from SQLite
    sqlite_conn = sqlite3.connect(db_path)
    sqlite_conn.row_factory = sqlite3.Row

    nodes = sqlite_conn.execute("SELECT * FROM nodes").fetchall()
    justifications = sqlite_conn.execute("SELECT * FROM justifications").fetchall()

    try:
        nogoods = sqlite_conn.execute("SELECT * FROM nogoods").fetchall()
    except sqlite3.OperationalError:
        nogoods = []

    sqlite_conn.close()

    print(f"Read from {db_path}:")
    print(f"  {len(nodes)} nodes, {len(justifications)} justifications, {len(nogoods)} nogoods")

    # Write to PostgreSQL
    pg = psycopg.connect(conninfo)

    with pg.cursor() as cur:
        # Create or get project
        cur.execute(
            "SELECT id FROM projects WHERE name = %s", (project_name,)
        )
        row = cur.fetchone()
        if row:
            project_id = str(row[0])
            print(f"Using existing project: {project_name} ({project_id})")

            # Clear existing RMS data for this project
            for table in ("rms_propagation_log", "rms_justifications",
                          "rms_nogoods", "rms_network_meta", "rms_nodes"):
                cur.execute(f"DELETE FROM {table} WHERE project_id = %s", (project_id,))
            print("  Cleared existing RMS data")
        else:
            cur.execute(
                "INSERT INTO projects (name, domain) VALUES (%s, %s) RETURNING id",
                (project_name, domain),
            )
            project_id = str(cur.fetchone()[0])
            print(f"Created project: {project_name} ({project_id})")

        # Bulk insert nodes
        for node in nodes:
            meta = node["metadata_json"] or "{}"
            cur.execute(
                "INSERT INTO rms_nodes (id, project_id, text, truth_value, source, source_hash, date, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (node["id"], project_id, node["text"], node["truth_value"],
                 node["source"] or "", node["source_hash"] or "",
                 node["date"] or "", meta),
            )

        # Bulk insert justifications
        for j in justifications:
            cur.execute(
                "INSERT INTO rms_justifications (node_id, project_id, type, antecedents, outlist, label) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (j["node_id"], project_id, j["type"],
                 j["antecedents_json"], j["outlist_json"], j["label"] or ""),
            )

        # Bulk insert nogoods
        for ng in nogoods:
            cur.execute(
                "INSERT INTO rms_nogoods (id, project_id, nodes, discovered, resolution) "
                "VALUES (%s, %s, %s, %s, %s)",
                (ng["id"], project_id, ng["nodes_json"] if "nodes_json" in ng.keys() else json.dumps(ng["nodes"]),
                 ng["discovered"] if "discovered" in ng.keys() else "",
                 ng["resolution"] if "resolution" in ng.keys() else ""),
            )

    pg.commit()
    pg.close()

    in_count = sum(1 for n in nodes if n["truth_value"] == "IN")
    print(f"\nLoaded into project '{project_name}':")
    print(f"  {len(nodes)} nodes ({in_count} IN, {len(nodes) - in_count} OUT)")
    print(f"  {len(justifications)} justifications")
    print(f"  {len(nogoods)} nogoods")
    print(f"\nTest with:")
    print(f"  expert-service  # start the server")
    print(f"  # then visit http://localhost:8000/projects/{project_id}/chat")


if __name__ == "__main__":
    main()

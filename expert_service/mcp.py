"""MCP server mounted at /mcp — exposes expert-service tools over streamable HTTP."""

import json

import httpx
from mcp.server.fastmcp import FastMCP

from expert_service.config import settings

mcp = FastMCP("expert-service", stateless_http=True)

BASE_URL = "http://localhost:8000"
TIMEOUT = 120.0


def _headers() -> dict[str, str]:
    if settings.api_key:
        return {"Authorization": f"Bearer {settings.api_key}"}
    return {}


def _resolve(project: str) -> str:
    if len(project) == 36 and project.count("-") == 4:
        return project
    resp = httpx.get(
        f"{BASE_URL}/api/projects/resolve",
        params={"name": project},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["id"]


# --- Tier 1: Core knowledge access ---


@mcp.tool()
def deep_search(query: str, project: str) -> str:
    """Search beliefs and source documents with IDF-ranked results. No LLM call, sub-second response.

    This is the recommended search tool. It runs dual-path retrieval across
    the belief network and source document chunks, returning pre-ranked
    context ready for synthesis.

    Args:
        query: The question or search terms
        project: Project name or UUID
    """
    pid = _resolve(project)
    resp = httpx.get(
        f"{BASE_URL}/api/projects/{pid}/deep-search",
        params={"q": query},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def ask(question: str, project: str) -> str:
    """Ask a question and get an LLM-synthesized answer grounded in the knowledge base.

    Slower than deep_search but returns a ready-to-use answer.

    Args:
        question: The question to ask
        project: Project name or UUID
    """
    pid = _resolve(project)
    resp = httpx.post(
        f"{BASE_URL}/api/projects/{pid}/ask",
        json={"question": question},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def search(query: str, project: str) -> str:
    """Full-text search across beliefs, entries, and source documents.

    Returns matching beliefs (with IN/OUT truth values), entry titles,
    and source chunk snippets.

    Args:
        query: Search terms
        project: Project name or UUID
    """
    pid = _resolve(project)
    resp = httpx.get(
        f"{BASE_URL}/api/projects/{pid}/search",
        params={"q": query},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


# --- Tier 2: Belief exploration ---


@mcp.tool()
def explain_belief(node_id: str, project: str) -> str:
    """Explain why a belief is IN or OUT by tracing its justification chain.

    Args:
        node_id: The belief ID to explain
        project: Project name or UUID
    """
    pid = _resolve(project)
    belief = httpx.get(
        f"{BASE_URL}/api/projects/{pid}/beliefs/{node_id}",
        headers=_headers(),
        timeout=TIMEOUT,
    )
    belief.raise_for_status()
    explanation = httpx.get(
        f"{BASE_URL}/api/projects/{pid}/beliefs/{node_id}/explain",
        headers=_headers(),
        timeout=TIMEOUT,
    )
    explanation.raise_for_status()
    return json.dumps({"belief": belief.json(), "explanation": explanation.json()}, indent=2)


@mcp.tool()
def what_if(node_id: str, action: str = "retract", project: str = "") -> str:
    """Simulate retracting or asserting a belief without modifying the database.

    Shows the cascade: which beliefs would go OUT (retract) or come back IN (assert).

    Args:
        node_id: The belief ID to simulate
        action: "retract" or "assert"
        project: Project name or UUID
    """
    pid = _resolve(project)
    resp = httpx.get(
        f"{BASE_URL}/api/projects/{pid}/beliefs/{node_id}/what-if",
        params={"action": action},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def get_belief(node_id: str, project: str) -> str:
    """Get full details for a specific belief including justifications and dependents.

    Args:
        node_id: The belief ID
        project: Project name or UUID
    """
    pid = _resolve(project)
    resp = httpx.get(
        f"{BASE_URL}/api/projects/{pid}/beliefs/{node_id}",
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def list_beliefs(status: str = "", project: str = "") -> str:
    """List beliefs in the knowledge base.

    Args:
        status: Filter by truth value -- "IN", "OUT", or empty for all
        project: Project name or UUID
    """
    pid = _resolve(project)
    params = {}
    if status:
        params["status"] = status
    resp = httpx.get(
        f"{BASE_URL}/api/projects/{pid}/beliefs",
        params=params,
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


# --- Tier 3: Content browsing ---


@mcp.tool()
def list_projects() -> str:
    """List all available expert knowledge bases with belief, entry, and source counts."""
    resp = httpx.get(
        f"{BASE_URL}/api/projects",
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def list_entries(topic: str = "", project: str = "") -> str:
    """List analysis entries (reports, findings, assessments).

    Args:
        topic: Filter by topic slug, or empty for all entries
        project: Project name or UUID
    """
    pid = _resolve(project)
    params = {}
    if topic:
        params["topic"] = topic
    resp = httpx.get(
        f"{BASE_URL}/api/projects/{pid}/entries",
        params=params,
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)


@mcp.tool()
def get_entry(entry_id: str, project: str) -> str:
    """Read the full content of an analysis entry.

    Args:
        entry_id: The entry ID
        project: Project name or UUID
    """
    pid = _resolve(project)
    resp = httpx.get(
        f"{BASE_URL}/api/projects/{pid}/entries/{entry_id}",
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return json.dumps(resp.json(), indent=2)

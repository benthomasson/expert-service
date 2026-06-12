"""MCP server mounted at /mcp — exposes expert-service tools over streamable HTTP."""

import json

import httpx
from mcp.server.fastmcp import FastMCP

from expert_service.config import settings

mcp = FastMCP(
    "expert-service",
    stateless_http=True,
    transport_security={"enable_dns_rebinding_protection": False},
)

BASE_URL = "http://localhost:8000"
TIMEOUT = 120.0


def _headers() -> dict[str, str]:
    if settings.api_key:
        return {"Authorization": f"Bearer {settings.api_key}"}
    return {}


async def _resolve(project: str) -> str:
    if len(project) == 36 and project.count("-") == 4:
        return project
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/projects/resolve",
            params={"name": project},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["id"]


# --- Tier 1: Core knowledge access ---


@mcp.tool()
async def deep_search(query: str, project: str) -> str:
    """Search beliefs and source documents with IDF-ranked results. No LLM call, sub-second response.

    This is the recommended search tool. It runs dual-path retrieval across
    the belief network and source document chunks, returning pre-ranked
    context ready for synthesis.

    Args:
        query: The question or search terms
        project: Project name or UUID
    """
    pid = await _resolve(project)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/projects/{pid}/deep-search",
            params={"q": query},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def ask(question: str, project: str) -> str:
    """Ask a question and get an LLM-synthesized answer grounded in the knowledge base.

    Slower than deep_search but returns a ready-to-use answer.

    Args:
        question: The question to ask
        project: Project name or UUID
    """
    pid = await _resolve(project)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/api/projects/{pid}/ask",
            json={"question": question},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def search(query: str, project: str) -> str:
    """Full-text search across beliefs, entries, and source documents.

    Returns matching beliefs (with IN/OUT truth values), entry titles,
    and source chunk snippets.

    Args:
        query: Search terms
        project: Project name or UUID
    """
    pid = await _resolve(project)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/projects/{pid}/search",
            params={"q": query},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


# --- Tier 2: Belief exploration ---


@mcp.tool()
async def explain_belief(node_id: str, project: str) -> str:
    """Explain why a belief is IN or OUT by tracing its justification chain.

    Args:
        node_id: The belief ID to explain
        project: Project name or UUID
    """
    pid = await _resolve(project)
    async with httpx.AsyncClient() as client:
        belief = await client.get(
            f"{BASE_URL}/api/projects/{pid}/beliefs/{node_id}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        belief.raise_for_status()
        explanation = await client.get(
            f"{BASE_URL}/api/projects/{pid}/beliefs/{node_id}/explain",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        explanation.raise_for_status()
        return json.dumps({"belief": belief.json(), "explanation": explanation.json()}, indent=2)


@mcp.tool()
async def what_if(node_id: str, action: str = "retract", project: str = "") -> str:
    """Simulate retracting or asserting a belief without modifying the database.

    Shows the cascade: which beliefs would go OUT (retract) or come back IN (assert).

    Args:
        node_id: The belief ID to simulate
        action: "retract" or "assert"
        project: Project name or UUID
    """
    pid = await _resolve(project)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/projects/{pid}/beliefs/{node_id}/what-if",
            params={"action": action},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def get_belief(node_id: str, project: str) -> str:
    """Get full details for a specific belief including justifications and dependents.

    Args:
        node_id: The belief ID
        project: Project name or UUID
    """
    pid = await _resolve(project)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/projects/{pid}/beliefs/{node_id}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def list_beliefs(status: str = "", project: str = "") -> str:
    """List beliefs in the knowledge base.

    Args:
        status: Filter by truth value -- "IN", "OUT", or empty for all
        project: Project name or UUID
    """
    pid = await _resolve(project)
    params = {}
    if status:
        params["status"] = status
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/projects/{pid}/beliefs",
            params=params,
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


# --- Tier 3: Content browsing ---


@mcp.tool()
async def list_projects() -> str:
    """List all available expert knowledge bases with belief, entry, and source counts."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/projects",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def list_entries(topic: str = "", project: str = "") -> str:
    """List analysis entries (reports, findings, assessments).

    Args:
        topic: Filter by topic slug, or empty for all entries
        project: Project name or UUID
    """
    pid = await _resolve(project)
    params = {}
    if topic:
        params["topic"] = topic
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/projects/{pid}/entries",
            params=params,
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def get_entry(entry_id: str, project: str) -> str:
    """Read the full content of an analysis entry.

    Args:
        entry_id: The entry ID
        project: Project name or UUID
    """
    pid = await _resolve(project)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/api/projects/{pid}/entries/{entry_id}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)

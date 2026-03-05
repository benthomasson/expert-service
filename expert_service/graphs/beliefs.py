"""Beliefs graph: propose beliefs from entries, human review, accept."""

from uuid import UUID

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select

from expert_service.core.propose import propose_from_entries
from expert_service.db.connection import get_sync_session
from expert_service.db.models import Claim, Entry
from expert_service.graphs.state import BeliefsState


def propose_beliefs(state: BeliefsState) -> dict:
    """Batch entries and extract belief candidates via LLM."""
    project_id = state["project_id"]
    batch_size = state.get("batch_size", 5)
    model = state.get("model")

    # Read all entries for this project
    with get_sync_session() as session:
        entries = session.execute(
            select(Entry)
            .where(Entry.project_id == UUID(project_id))
            .order_by(Entry.topic)
        ).scalars().all()

        entry_dicts = [
            {
                "id": entry.id,
                "topic": entry.topic,
                "title": entry.title,
                "content": entry.content,
            }
            for entry in entries
        ]

    if not entry_dicts:
        return {
            "proposed_beliefs": [],
            "errors": ["No entries found for this project"],
        }

    # Extract beliefs via LLM
    beliefs = propose_from_entries(entry_dicts, model=model, batch_size=batch_size)

    # Write proposed beliefs to claims table
    with get_sync_session() as session:
        for belief in beliefs:
            claim = Claim(
                id=belief["id"],
                project_id=UUID(project_id),
                text=belief["text"],
                status="PROPOSED",
                source=belief.get("source", ""),
                review_status="pending",
            )
            session.merge(claim)
        session.commit()

    return {
        "proposed_beliefs": beliefs,
        "errors": [],
    }


def human_review(state: BeliefsState) -> dict:
    """Pause for human review of proposed beliefs."""
    proposed = state.get("proposed_beliefs", [])
    if not proposed:
        return {"review_decisions": {}}

    review = interrupt({
        "proposed_beliefs": proposed,
        "message": f"Review {len(proposed)} proposed beliefs",
    })
    return {"review_decisions": review}


def accept_beliefs(state: BeliefsState) -> dict:
    """Update claims in DB based on review decisions."""
    project_id = state["project_id"]
    decisions = state.get("review_decisions", {})

    accepted = 0
    rejected = 0

    with get_sync_session() as session:
        for belief_id, decision in decisions.items():
            claim = session.execute(
                select(Claim).where(
                    Claim.id == belief_id,
                    Claim.project_id == UUID(project_id),
                )
            ).scalar_one_or_none()

            if not claim:
                continue

            if decision == "accept":
                claim.status = "IN"
                claim.review_status = "accepted"
                accepted += 1
            elif decision == "reject":
                claim.status = "OUT"
                claim.review_status = "rejected"
                rejected += 1

        session.commit()

    return {
        "accepted_count": accepted,
        "rejected_count": rejected,
    }


# Build the graph
builder = StateGraph(BeliefsState)
builder.add_node("propose_beliefs", propose_beliefs)
builder.add_node("human_review", human_review)
builder.add_node("accept_beliefs", accept_beliefs)

builder.set_entry_point("propose_beliefs")
builder.add_edge("propose_beliefs", "human_review")
builder.add_edge("human_review", "accept_beliefs")
builder.add_edge("accept_beliefs", END)

# For LangGraph Platform (provides its own checkpointer)
beliefs_graph = builder.compile()

# For direct API use (we provide our own checkpointer for interrupt support)
_api_graph = None


def get_beliefs_graph():
    """Get beliefs graph compiled with PostgresSaver checkpointer.

    interrupt() requires a checkpointer to persist state while paused.
    LangGraph Platform provides its own; for direct API use we need ours.
    """
    global _api_graph
    if _api_graph is None:
        from expert_service.graphs.checkpointer import get_checkpointer
        _api_graph = builder.compile(checkpointer=get_checkpointer())
    return _api_graph

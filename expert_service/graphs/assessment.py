"""Assessment graph: cert coverage analysis and practice exams."""

import hashlib
from uuid import UUID

from langgraph.graph import END, StateGraph
from sqlalchemy import select

from expert_service.core.coverage import match_objectives
from expert_service.core.exam import run_exam_questions
from expert_service.db.connection import get_sync_session
from expert_service.db.models import Assessment, Claim, Nogood
from expert_service.graphs.state import AssessmentState


def load_beliefs(state: AssessmentState) -> dict:
    """Load all IN beliefs for the project as context."""
    project_id = state["project_id"]

    with get_sync_session() as session:
        claims = session.execute(
            select(Claim)
            .where(
                Claim.project_id == UUID(project_id),
                Claim.status == "IN",
            )
            .order_by(Claim.id)
        ).scalars().all()

    if not claims:
        return {"beliefs_context": "(No IN beliefs found)"}

    context = "\n".join(f"- {c.id}: {c.text}" for c in claims)
    return {"beliefs_context": context}


def run_coverage(state: AssessmentState) -> dict:
    """Check belief coverage against certification objectives."""
    project_id = state["project_id"]
    objectives = state.get("objectives", [])
    model = state.get("model")

    if not objectives:
        return {"results": [], "score": {"covered": 0, "total": 0, "pct": 0}}

    # Parse beliefs from context back to dicts for matching
    beliefs = _parse_beliefs_context(state.get("beliefs_context", ""))

    outcome = match_objectives(objectives, beliefs, model=model)

    # Save assessment to DB
    with get_sync_session() as session:
        assessment = Assessment(
            project_id=UUID(project_id),
            assessment_type="coverage",
            input_data={"objectives_count": len(objectives)},
            results={"details": _serialize_results(outcome["results"])},
            score=outcome["score"],
        )
        session.add(assessment)
        session.commit()

    return {
        "results": outcome["results"],
        "score": outcome["score"],
    }


def run_exam(state: AssessmentState) -> dict:
    """Run practice exam questions against beliefs."""
    project_id = state["project_id"]
    questions = state.get("questions", [])
    domain = state.get("domain", "")
    model = state.get("model")
    beliefs_context = state.get("beliefs_context", "")

    if not questions:
        return {
            "results": [],
            "score": {"correct": 0, "total": 0, "pct": 0},
            "nogoods_discovered": [],
        }

    outcome = run_exam_questions(
        questions, beliefs_context, domain=domain, model=model,
    )

    # Save assessment and nogoods to DB
    with get_sync_session() as session:
        assessment = Assessment(
            project_id=UUID(project_id),
            assessment_type="exam",
            input_data={"questions_count": len(questions)},
            results={"details": _serialize_exam_results(outcome["results"])},
            score=outcome["score"],
        )
        session.add(assessment)

        # Record nogoods for wrong answers
        for ng in outcome["nogoods"]:
            nogood_id = hashlib.sha256(
                ng["description"].encode()
            ).hexdigest()[:12]
            nogood = Nogood(
                id=nogood_id,
                project_id=UUID(project_id),
                description=ng["description"],
                resolution=ng["resolution"],
            )
            session.merge(nogood)

        session.commit()

    return {
        "results": outcome["results"],
        "score": outcome["score"],
        "nogoods_discovered": outcome["nogoods"],
    }


def route_assessment(state: AssessmentState) -> str:
    """Route to coverage or exam based on assessment_type."""
    if state["assessment_type"] == "coverage":
        return "run_coverage"
    return "run_exam"


def _parse_beliefs_context(context: str) -> list[dict]:
    """Parse beliefs context string back to list of dicts."""
    beliefs = []
    for line in context.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            line = line[2:]
            if ": " in line:
                bid, text = line.split(": ", 1)
                beliefs.append({"id": bid.strip(), "text": text.strip()})
    return beliefs


def _serialize_results(results: list[dict]) -> list[dict]:
    """Serialize coverage results for JSON storage."""
    return [
        {
            "objective_id": r["objective"]["id"],
            "objective_text": r["objective"]["text"],
            "domain": r["objective"].get("domain", "general"),
            "covered": r["covered"],
            "matches": r["matches"],
        }
        for r in results
    ]


def _serialize_exam_results(results: list[dict]) -> list[dict]:
    """Serialize exam results for JSON storage."""
    return [
        {
            "question_id": r["question"]["id"],
            "question_text": r["question"]["text"],
            "status": r["status"],
            "got": r.get("got"),
            "expected": r.get("expected"),
        }
        for r in results
    ]


# Build the graph
builder = StateGraph(AssessmentState)
builder.add_node("load_beliefs", load_beliefs)
builder.add_node("run_coverage", run_coverage)
builder.add_node("run_exam", run_exam)

builder.set_entry_point("load_beliefs")
builder.add_conditional_edges("load_beliefs", route_assessment)
builder.add_edge("run_coverage", END)
builder.add_edge("run_exam", END)

assessment_graph = builder.compile()

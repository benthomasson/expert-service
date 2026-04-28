"""Lightweight belief-search endpoint — no LLM, just FTS."""

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from expert_service.rms import api as rms_api

router = APIRouter(prefix="/api/projects/{project_id}", tags=["ask"])


class AskRequest(BaseModel):
    question: str


@router.post("/ask")
async def ask(project_id: UUID, data: AskRequest):
    result = rms_api.search(project_id, data.question)
    compact = "\n".join(
        f"[{r['truth_value']}] {r['id']} — {r['text']}"
        for r in result["results"]
    )
    return {
        "question": data.question,
        "beliefs": result["results"],
        "count": result["count"],
        "compact": compact,
    }

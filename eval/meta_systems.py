"""Meta-expert evaluation driver — calls /api/meta/chat and captures routing."""

import json
import time
from dataclasses import dataclass, field
from uuid import uuid4

import httpx

from eval.systems import DriverResponse


@dataclass
class MetaResponse(DriverResponse):
    """Extends DriverResponse with meta-expert-specific fields."""
    experts_consulted: list[str] = field(default_factory=list)
    reflection_calls: list[dict] = field(default_factory=list)
    expert_citations: list[str] = field(default_factory=list)


class MetaExpertDriver:
    """Call meta-expert chat API with SSE streaming.

    Captures ask_expert tool calls for routing evaluation,
    reflection rms_add calls, and citation references.
    """

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def ask(self, question: str) -> MetaResponse:
        url = f"{self.base_url}/api/meta/chat"
        payload = {
            "message": question,
            "model": self.model,
            "thread_id": str(uuid4()),
        }

        tokens: list[str] = []
        tool_calls: list[dict] = []
        experts_consulted: list[str] = []
        reflection_calls: list[dict] = []
        current_event: str | None = None

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        current_event = None
                        continue
                    if line.startswith("event: "):
                        current_event = line[7:]
                    elif line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue

                        if current_event == "tool_call":
                            tool_calls.append({
                                "name": data.get("name", "unknown"),
                                "args": data.get("args", {}),
                            })
                            # Track which experts were consulted
                            if data.get("name") == "ask_expert":
                                expert = data["args"].get("expert_name", "")
                                if expert and expert not in experts_consulted:
                                    experts_consulted.append(expert)

                        elif current_event == "reflection":
                            reflection_calls.append({
                                "name": data.get("name", "unknown"),
                                "args": data.get("args", {}),
                            })

                        elif current_event == "done":
                            # Keep reading for reflection events after done
                            pass

                        elif data.get("type") == "token":
                            tokens.append(data.get("content", ""))

        elapsed = time.monotonic() - t0
        answer_text = "".join(tokens)

        # Extract citation references from the answer
        import re
        citations = re.findall(r'belief[:\s]+(?:ID[:\s]+)?([a-z0-9][a-z0-9._-]*)', answer_text, re.IGNORECASE)
        citations = [c.lower().rstrip(".,;:") for c in citations]

        return MetaResponse(
            text=answer_text,
            tool_calls=tool_calls,
            latency_seconds=elapsed,
            experts_consulted=experts_consulted,
            reflection_calls=reflection_calls,
            expert_citations=list(dict.fromkeys(citations)),  # dedupe preserving order
        )

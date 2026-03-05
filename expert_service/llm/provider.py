"""LLM provider factory — returns LangChain ChatModel instances via Vertex AI.

Uses the same Vertex AI OAuth credentials as agents-python.
Auth: gcloud auth application-default login
"""

from langchain_google_vertexai import ChatVertexAI
from langchain_google_vertexai.model_garden import ChatAnthropicVertex

from expert_service.config import settings

# Claude on Vertex AI requires us-east5
CLAUDE_LOCATION = "us-east5"


def get_chat_model(model: str | None = None):
    """Return a ChatModel instance for the given model name.

    Both Gemini and Claude are accessed through Vertex AI,
    reusing the same GCP project and ADC credentials as agents-python.
    Claude uses ChatAnthropicVertex (Anthropic publisher), Gemini uses ChatVertexAI.
    """
    model = model or settings.default_model

    if "claude" in model:
        return ChatAnthropicVertex(
            model_name=model,
            project=settings.google_cloud_project,
            location=CLAUDE_LOCATION,
            max_tokens=4096,
        )
    elif "gemini" in model:
        return ChatVertexAI(
            model_name=model,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )
    else:
        raise ValueError(f"Unknown model: {model}")

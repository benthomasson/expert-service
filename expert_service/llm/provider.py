"""LLM provider factory — returns LangChain ChatModel instances."""

from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI

from expert_service.config import settings


def get_chat_model(model: str | None = None):
    """Return a ChatModel instance for the given model name."""
    model = model or settings.default_model

    if "claude" in model:
        return ChatAnthropic(
            model=model,
            api_key=settings.anthropic_api_key,
            max_tokens=4096,
        )
    elif "gemini" in model:
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.google_api_key,
        )
    else:
        raise ValueError(f"Unknown model: {model}")

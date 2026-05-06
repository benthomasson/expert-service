"""Application configuration."""

import os
from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://expert:expert_dev@localhost:5432/expert_service",
    )
    # Sync URL for LangGraph checkpointer (uses psycopg, not asyncpg)
    database_url_sync: str = os.getenv(
        "DATABASE_URL_SYNC",
        "postgresql+psycopg://expert:expert_dev@localhost:5432/expert_service",
    )
    # Vertex AI configuration (shared with agents-python)
    google_cloud_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    google_cloud_location: str = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    default_model: str = os.getenv("DEFAULT_MODEL", "claude-sonnet-4-20250514")
    # Ollama configuration (optional — for local model serving)
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    # LangFuse tracing (optional — disabled when secret_key is empty)
    langfuse_secret_key: str = os.getenv("LANGFUSE_SECRET_KEY", "")
    langfuse_public_key: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_host: str = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
    # Auth (optional — when unset, dev mode allows anonymous access)
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    secret_key: str = os.getenv("SECRET_KEY", "dev-insecure-key")
    api_key: str = os.getenv("EXPERT_SERVICE_API_KEY", "")
    allowed_emails: str = os.getenv("ALLOWED_EMAILS", "")


settings = Settings()

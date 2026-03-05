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
        "postgresql://expert:expert_dev@localhost:5432/expert_service",
    )
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
    default_model: str = os.getenv("DEFAULT_MODEL", "claude-sonnet-4-20250514")


settings = Settings()

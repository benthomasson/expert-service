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
    default_model: str = os.getenv("DEFAULT_MODEL", "gemini-2.5-pro")


settings = Settings()

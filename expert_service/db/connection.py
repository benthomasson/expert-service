"""Database connection management."""

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession

from expert_service.config import settings

# Async engine for FastAPI request handlers
engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine for LangGraph graph nodes (which are synchronous)
_sync_engine = None


def get_sync_engine():
    """Lazy-initialized sync engine for graph nodes."""
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(settings.database_url_sync, echo=False)
    return _sync_engine


def get_sync_session() -> SyncSession:
    """Create a sync database session for use in graph nodes."""
    return SyncSession(get_sync_engine())


async def get_session():
    """FastAPI dependency for async database sessions."""
    async with async_session() as session:
        yield session

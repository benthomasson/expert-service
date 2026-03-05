"""LangGraph checkpointer setup."""

from langgraph.checkpoint.postgres import PostgresSaver

from expert_service.config import settings


def get_checkpointer() -> PostgresSaver:
    """Create a PostgresSaver checkpointer for LangGraph graphs."""
    checkpointer = PostgresSaver.from_conn_string(settings.database_url_sync)
    checkpointer.setup()
    return checkpointer

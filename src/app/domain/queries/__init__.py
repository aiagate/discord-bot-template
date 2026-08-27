"""Query interfaces for the domain layer."""

from app.domain.queries.chat_history_query import IChatHistoryQuery
from app.domain.queries.raw_chat_log_query import IRawChatLogQuery

__all__ = ["IChatHistoryQuery", "IRawChatLogQuery"]

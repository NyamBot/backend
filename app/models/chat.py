from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChatMessage:
    """Domain model for one user or assistant chat message."""

    id: str
    session_id: str | None
    user_id: str | None
    role: str
    content: str
    retrieved_context: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None


@dataclass(frozen=True)
class ChatSession:
    """Domain model for a chat session that groups messages."""

    id: str
    user_id: str | None
    title: str
    created_at: str
    updated_at: str
    messages: list[ChatMessage] = field(default_factory=list)

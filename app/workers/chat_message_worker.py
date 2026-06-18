from __future__ import annotations

import logging
from typing import Any

from app.services.chat_message_queue import chat_message_queue
from app.services.restaurant_store import restaurant_store


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def handle_job(payload: dict[str, Any]) -> None:
    if payload.get("task") != chat_message_queue.task_type:
        raise ValueError(f"Unsupported task type: {payload.get('task')}")

    message = payload.get("message")
    if not isinstance(message, dict):
        raise ValueError("Chat message job is missing a message payload")

    restaurant_store.save_message(
        session_id=str(message["session_id"]),
        user_id=message.get("user_id"),
        role=str(message["role"]),
        content=str(message["content"]),
        retrieved_context=list(message.get("retrieved_context") or []),
        metadata=dict(message.get("metadata") or {}),
    )
    logger.info(
        "Saved %s chat message for session %s",
        message.get("role"),
        message.get("session_id"),
    )


def main() -> None:
    chat_message_queue.consume_forever(handle_job)


if __name__ == "__main__":
    main()

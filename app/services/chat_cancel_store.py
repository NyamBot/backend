from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class ActiveChatRequest:
    user_id: str
    session_id: str


class ChatCancelStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active_requests: dict[str, ActiveChatRequest] = {}
        self._cancelled_request_ids: set[str] = set()

    def register(self, user_id: str, session_id: str, request_id: str) -> None:
        with self._lock:
            self._active_requests[request_id] = ActiveChatRequest(user_id=user_id, session_id=session_id)

    def cancel(
        self,
        user_id: str,
        session_id: str | None = None,
        request_id: str | None = None,
    ) -> bool:
        with self._lock:
            if request_id:
                active = self._active_requests.get(request_id)
                if active is None or active.user_id != user_id:
                    return False
                self._cancelled_request_ids.add(request_id)
                return True

            if session_id:
                matched_request_ids = [
                    active_request_id
                    for active_request_id, active in self._active_requests.items()
                    if active.user_id == user_id and active.session_id == session_id
                ]
                self._cancelled_request_ids.update(matched_request_ids)
                return bool(matched_request_ids)

        return False

    def is_cancelled(self, request_id: str) -> bool:
        with self._lock:
            return request_id in self._cancelled_request_ids

    def complete(self, request_id: str) -> None:
        with self._lock:
            self._active_requests.pop(request_id, None)
            self._cancelled_request_ids.discard(request_id)


chat_cancel_store = ChatCancelStore()

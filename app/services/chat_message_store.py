from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.schemas import TasteAgentMessage


class OpenSearchChatMessageStore:
    def __init__(self) -> None:
        self.index_name = settings.opensearch_chat_messages_index
        self._client: Any | None = None
        self._index_ready = False

    @property
    def enabled(self) -> bool:
        return settings.chat_message_backend.lower() == "opensearch"

    def save_message(
        self,
        session_id: str,
        user_id: str | None,
        role: str,
        content: str,
        retrieved_context: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> TasteAgentMessage:
        self._ensure_index()
        message_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        document = {
            "id": message_id,
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "retrieved_context": retrieved_context,
            "metadata": metadata or {},
            "created_at": created_at,
        }
        self._client.index(index=self.index_name, id=message_id, body=document, refresh=True)
        return self._message_from_document(document)

    def list_messages(
        self,
        user_id: str | None,
        session_id: str | None = None,
        session_ids: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[TasteAgentMessage], bool]:
        self._ensure_index()
        filters: list[dict[str, Any]] = []
        if user_id:
            filters.append({"term": {"user_id": user_id}})
        if session_id:
            filters.append({"term": {"session_id": session_id}})
        if session_ids:
            filters.append({"terms": {"session_id": session_ids}})

        if filters:
            query: dict[str, Any] = {"bool": {"filter": filters}}
        else:
            query = {"match_all": {}}
        page_size = max(limit, 0) + 1
        response = self._client.search(
            index=self.index_name,
            body={
                "query": query,
                "sort": [{"created_at": {"order": "asc"}}],
                "from": max(offset, 0),
                "size": page_size,
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        messages = [self._message_from_document(hit["_source"]) for hit in hits[:limit]]
        return messages, len(hits) > limit

    def delete_user_messages(self, user_id: str) -> None:
        self._ensure_index()
        self._client.delete_by_query(
            index=self.index_name,
            body={"query": {"term": {"user_id": user_id}}},
            refresh=True,
            conflicts="proceed",
        )

    def _ensure_index(self) -> None:
        if self._index_ready:
            return
        client = self._get_client()
        if not client.indices.exists(index=self.index_name):
            client.indices.create(
                index=self.index_name,
                body={
                    "mappings": {
                        "properties": {
                            "id": {"type": "keyword"},
                            "session_id": {"type": "keyword"},
                            "user_id": {"type": "keyword"},
                            "role": {"type": "keyword"},
                            "content": {"type": "text"},
                            "retrieved_context": {"type": "text"},
                            "metadata": {"type": "object", "enabled": True},
                            "created_at": {"type": "date"},
                        }
                    }
                },
            )
        self._index_ready = True

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from opensearchpy import OpenSearch
        except ImportError as error:
            raise RuntimeError("opensearch-py is not installed") from error

        http_auth = None
        if settings.opensearch_username and settings.opensearch_password:
            http_auth = (settings.opensearch_username, settings.opensearch_password)
        self._client = OpenSearch(
            hosts=[settings.opensearch_url],
            http_auth=http_auth,
            use_ssl=settings.opensearch_url.startswith("https://"),
            verify_certs=settings.opensearch_verify_certs,
            timeout=5,
            max_retries=1,
            retry_on_timeout=False,
        )
        return self._client

    def _message_from_document(self, document: dict[str, Any]) -> TasteAgentMessage:
        return TasteAgentMessage(
            id=str(document["id"]),
            session_id=document.get("session_id"),
            user_id=document.get("user_id"),
            role=str(document["role"]),
            content=str(document["content"]),
            retrieved_context=list(document.get("retrieved_context") or []),
            metadata=dict(document.get("metadata") or {}),
            created_at=str(document["created_at"]),
        )


chat_message_store = OpenSearchChatMessageStore()

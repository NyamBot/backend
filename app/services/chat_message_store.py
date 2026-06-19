from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.schemas import TasteAgentMessage


_INDEX_TIMEZONE = timezone(timedelta(hours=9))


class OpenSearchChatMessageStore:
    def __init__(self) -> None:
        self.index_prefix = settings.opensearch_chat_messages_index.rstrip("-")
        self._client: Any | None = None
        self._ready_indices: set[str] = set()

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
        message_id = str(uuid4())
        created_at_datetime = datetime.now(timezone.utc)
        created_at = created_at_datetime.isoformat()
        index_name = self._index_name_for_datetime(created_at_datetime)
        self._ensure_index(index_name)
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
        self._client.index(index=index_name, id=message_id, body=document)
        return self._message_from_document(document)

    def list_messages(
        self,
        user_id: str | None,
        session_id: str | None = None,
        session_ids: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[TasteAgentMessage], bool]:
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
        client = self._get_client()
        response = client.search(
            index=self._search_index_pattern(),
            body={
                "query": query,
                "sort": [{"created_at": {"order": "asc"}}],
                "from": max(offset, 0),
                "size": page_size,
            },
            ignore_unavailable=True,
        )
        hits = response.get("hits", {}).get("hits", [])
        messages = [self._message_from_document(hit["_source"]) for hit in hits[:limit]]
        return messages, len(hits) > limit

    def delete_user_messages(self, user_id: str) -> None:
        client = self._get_client()
        client.delete_by_query(
            index=self._search_index_pattern(),
            body={"query": {"term": {"user_id": user_id}}},
            refresh=True,
            conflicts="proceed",
            ignore_unavailable=True,
        )

    def _ensure_index(self, index_name: str) -> None:
        if index_name in self._ready_indices:
            return
        client = self._get_client()
        if not client.indices.exists(index=index_name):
            client.indices.create(
                index=index_name,
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
        self._ready_indices.add(index_name)

    def _index_name_for_datetime(self, created_at: datetime) -> str:
        partition_time = created_at.astimezone(_INDEX_TIMEZONE)
        suffix = "0106" if partition_time.month <= 6 else "0712"
        return f"{self.index_prefix}-{partition_time.year}-{suffix}"

    def _search_index_pattern(self) -> str:
        return f"{self.index_prefix}-*"

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

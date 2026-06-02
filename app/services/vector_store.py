from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services.chunker import chunk_text


VECTOR_DIMENSIONS = 96


def _embed(text: str) -> list[float]:
    vector = [0.0] * VECTOR_DIMENSIONS
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % VECTOR_DIMENSIONS
        vector[index] += 1.0

    magnitude = math.sqrt(sum(value * value for value in vector))
    if not magnitude:
        return vector
    return [value / magnitude for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _embedding_to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(str(value) for value in vector) + "]"


def _mask_database_url(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    return f"{scheme}://***@{rest.split('@', 1)[1]}"


class SqliteVectorStore:
    def __init__(self, database_url: str) -> None:
        if not database_url.startswith("sqlite:///"):
            raise ValueError("SQLite URL must start with sqlite:///")
        database_path = Path(database_url.removeprefix("sqlite:///"))
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    avatar_url TEXT,
                    auth_provider TEXT NOT NULL DEFAULT 'demo',
                    provider_subject TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_login_at TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_provider_subject
                    ON users(auth_provider, provider_subject)
                    WHERE provider_subject IS NOT NULL;

                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                    title TEXT NOT NULL,
                    audience TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    tone TEXT NOT NULL,
                    goal TEXT NOT NULL DEFAULT 'awareness',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS source_chunks (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    document TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_source_chunks_source_id
                    ON source_chunks(source_id);
                """
            )
            self._ensure_sqlite_column(connection, "sources", "user_id", "TEXT REFERENCES users(id) ON DELETE SET NULL")
            self._ensure_sqlite_column(connection, "sources", "goal", "TEXT NOT NULL DEFAULT 'awareness'")

    def _ensure_sqlite_column(
        self,
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_user(
        self,
        email: str,
        display_name: str,
        avatar_url: str | None,
        auth_provider: str,
        provider_subject: str | None,
    ) -> dict[str, Any]:
        user_id = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users
                    (id, email, display_name, avatar_url, auth_provider, provider_subject)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, email, display_name, avatar_url, auth_provider, provider_subject),
            )
        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError("Created user could not be loaded")
        return user

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, email, display_name, avatar_url, auth_provider,
                    provider_subject, created_at, last_login_at
                FROM users
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, email, display_name, avatar_url, auth_provider,
                    provider_subject, created_at, last_login_at
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def add_source(self, title: str, transcript: str, metadata: dict[str, str]) -> tuple[str, int]:
        source_id = str(uuid4())
        chunks = chunk_text(transcript)
        user_id = metadata.get("user_id") or None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sources (id, user_id, title, audience, platform, tone, goal)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    user_id,
                    title,
                    metadata.get("audience", "general creators"),
                    metadata.get("platform", "shorts"),
                    metadata.get("tone", "clear, energetic"),
                    metadata.get("goal", "awareness"),
                ),
            )
            connection.executemany(
                """
                INSERT INTO source_chunks
                    (id, source_id, chunk_index, document, embedding_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"{source_id}:{index}",
                        source_id,
                        index,
                        chunk,
                        json.dumps(_embed(chunk)),
                    )
                    for index, chunk in enumerate(chunks)
                ],
            )
        return source_id, len(chunks)

    def list_sources(self, user_id: str | None = None) -> list[dict[str, Any]]:
        where_clause = "WHERE sources.user_id = ?" if user_id else ""
        params = (user_id,) if user_id else ()
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    sources.id,
                    sources.user_id,
                    sources.title,
                    sources.audience,
                    sources.platform,
                    sources.tone,
                    sources.goal,
                    sources.created_at,
                    COUNT(source_chunks.id) AS chunk_count
                FROM sources
                LEFT JOIN source_chunks ON source_chunks.source_id = sources.id
                {where_clause}
                GROUP BY sources.id
                ORDER BY sources.created_at DESC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    sources.id,
                    sources.user_id,
                    sources.title,
                    sources.audience,
                    sources.platform,
                    sources.tone,
                    sources.goal,
                    sources.created_at,
                    COUNT(source_chunks.id) AS chunk_count
                FROM sources
                LEFT JOIN source_chunks ON source_chunks.source_id = sources.id
                WHERE sources.id = ?
                GROUP BY sources.id
                """,
                (source_id,),
            ).fetchone()
        return dict(row) if row else None

    def search(self, source_id: str, query: str, limit: int = 5) -> list[str]:
        query_embedding = _embed(query)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT document, embedding_json
                FROM source_chunks
                WHERE source_id = ?
                """,
                (source_id,),
            ).fetchall()
        ranked = sorted(
            rows,
            key=lambda row: _cosine(json.loads(row["embedding_json"]), query_embedding),
            reverse=True,
        )
        return [row["document"] for row in ranked[:limit]]


class PgVectorStore:
    def __init__(self, database_url: str) -> None:
        import psycopg
        from psycopg.rows import dict_row

        self.database_url = database_url
        self.psycopg = psycopg
        self.dict_row = dict_row
        self._init_schema()

    def _connect(self):
        return self.psycopg.connect(self.database_url)

    def _init_schema(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        email TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        avatar_url TEXT,
                        auth_provider TEXT NOT NULL DEFAULT 'demo',
                        provider_subject TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_login_at TIMESTAMPTZ
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_users_provider_subject
                        ON users(auth_provider, provider_subject)
                        WHERE provider_subject IS NOT NULL
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sources (
                        id TEXT PRIMARY KEY,
                        user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                        title TEXT NOT NULL,
                        audience TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        tone TEXT NOT NULL,
                        goal TEXT NOT NULL DEFAULT 'awareness',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS source_chunks (
                        id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                        chunk_index INTEGER NOT NULL,
                        document TEXT NOT NULL,
                        embedding VECTOR({VECTOR_DIMENSIONS}) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_source_chunks_source_id
                        ON source_chunks(source_id)
                    """
                )
                self._ensure_pg_column(cursor, "sources", "user_id", "TEXT REFERENCES users(id) ON DELETE SET NULL")
                self._ensure_pg_column(cursor, "sources", "goal", "TEXT NOT NULL DEFAULT 'awareness'")
                connection.commit()
                try:
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_source_chunks_embedding
                            ON source_chunks USING hnsw (embedding vector_cosine_ops)
                        """
                    )
                except Exception:
                    connection.rollback()

    def _ensure_pg_column(self, cursor: Any, table: str, column: str, definition: str) -> None:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            (table, column),
        )
        if cursor.fetchone() is None:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_user(
        self,
        email: str,
        display_name: str,
        avatar_url: str | None,
        auth_provider: str,
        provider_subject: str | None,
    ) -> dict[str, Any]:
        user_id = str(uuid4())
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users
                        (id, email, display_name, avatar_url, auth_provider, provider_subject)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, email, display_name, avatar_url, auth_provider, provider_subject),
                )
        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError("Created user could not be loaded")
        return user

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, email, display_name, avatar_url, auth_provider,
                        provider_subject, created_at::text AS created_at,
                        last_login_at::text AS last_login_at
                    FROM users
                    ORDER BY created_at DESC
                    """
                )
                return list(cursor.fetchall())

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, email, display_name, avatar_url, auth_provider,
                        provider_subject, created_at::text AS created_at,
                        last_login_at::text AS last_login_at
                    FROM users
                    WHERE id = %s
                    """,
                    (user_id,),
                )
                return cursor.fetchone()

    def add_source(self, title: str, transcript: str, metadata: dict[str, str]) -> tuple[str, int]:
        source_id = str(uuid4())
        chunks = chunk_text(transcript)
        user_id = metadata.get("user_id") or None
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO sources (id, user_id, title, audience, platform, tone, goal)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        source_id,
                        user_id,
                        title,
                        metadata.get("audience", "general creators"),
                        metadata.get("platform", "shorts"),
                        metadata.get("tone", "clear, energetic"),
                        metadata.get("goal", "awareness"),
                    ),
                )
                cursor.executemany(
                    """
                    INSERT INTO source_chunks
                        (id, source_id, chunk_index, document, embedding)
                    VALUES (%s, %s, %s, %s, %s::vector)
                    """,
                    [
                        (
                            f"{source_id}:{index}",
                            source_id,
                            index,
                            chunk,
                            _embedding_to_pgvector(_embed(chunk)),
                        )
                        for index, chunk in enumerate(chunks)
                    ],
                )
        return source_id, len(chunks)

    def list_sources(self, user_id: str | None = None) -> list[dict[str, Any]]:
        where_clause = "WHERE sources.user_id = %s" if user_id else ""
        params = (user_id,) if user_id else ()
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        sources.id,
                        sources.user_id,
                        sources.title,
                        sources.audience,
                        sources.platform,
                        sources.tone,
                        sources.goal,
                        sources.created_at::text AS created_at,
                        COUNT(source_chunks.id)::int AS chunk_count
                    FROM sources
                    LEFT JOIN source_chunks ON source_chunks.source_id = sources.id
                    {where_clause}
                    GROUP BY sources.id
                    ORDER BY sources.created_at DESC
                    """,
                    params,
                )
                return list(cursor.fetchall())

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        sources.id,
                        sources.user_id,
                        sources.title,
                        sources.audience,
                        sources.platform,
                        sources.tone,
                        sources.goal,
                        sources.created_at::text AS created_at,
                        COUNT(source_chunks.id)::int AS chunk_count
                    FROM sources
                    LEFT JOIN source_chunks ON source_chunks.source_id = sources.id
                    WHERE sources.id = %s
                    GROUP BY sources.id
                    """,
                    (source_id,),
                )
                return cursor.fetchone()

    def search(self, source_id: str, query: str, limit: int = 5) -> list[str]:
        query_embedding = _embedding_to_pgvector(_embed(query))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT document
                    FROM source_chunks
                    WHERE source_id = %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (source_id, query_embedding, limit),
                )
                return [row[0] for row in cursor.fetchall()]


class VectorStore:
    def __init__(self) -> None:
        self.database_url = _mask_database_url(settings.database_url)
        try:
            if settings.database_url.startswith(("postgresql://", "postgres://")):
                self.backend = PgVectorStore(settings.database_url)
                self.backend_name = "pgvector"
            elif settings.database_url.startswith("sqlite:///"):
                self.backend = SqliteVectorStore(settings.database_url)
                self.backend_name = "sqlite-vector"
            else:
                raise ValueError("Unsupported DATABASE_URL")
        except Exception:
            self.backend = SqliteVectorStore("sqlite:///./data/clipforge.db")
            self.backend_name = "sqlite-vector"
            self.database_url = "sqlite:///./data/clipforge.db"

    def add_source(self, title: str, transcript: str, metadata: dict[str, str]) -> tuple[str, int]:
        return self.backend.add_source(title, transcript, metadata)

    def create_user(
        self,
        email: str,
        display_name: str,
        avatar_url: str | None,
        auth_provider: str,
        provider_subject: str | None,
    ) -> dict[str, Any]:
        return self.backend.create_user(
            email=email,
            display_name=display_name,
            avatar_url=avatar_url,
            auth_provider=auth_provider,
            provider_subject=provider_subject,
        )

    def list_users(self) -> list[dict[str, Any]]:
        return self.backend.list_users()

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self.backend.get_user(user_id)

    def list_sources(self, user_id: str | None = None) -> list[dict[str, Any]]:
        if hasattr(self.backend, "list_sources"):
            return self.backend.list_sources(user_id=user_id)
        return []

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        if hasattr(self.backend, "get_source"):
            return self.backend.get_source(source_id)
        return None

    def search(self, source_id: str, query: str, limit: int = 5) -> list[str]:
        return self.backend.search(source_id, query, limit)


vector_store = VectorStore()

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.schemas import AgentMessage, ClipIdea, ScriptPack
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

                CREATE TABLE IF NOT EXISTS clip_ideas (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    hook TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    hook_score INTEGER NOT NULL,
                    audience_angle TEXT NOT NULL,
                    cta TEXT NOT NULL,
                    platform_fit TEXT NOT NULL,
                    source_moments_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_clip_ideas_source_id
                    ON clip_ideas(source_id);

                CREATE TABLE IF NOT EXISTS campaign_packs (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    clip_idea_id TEXT NOT NULL REFERENCES clip_ideas(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    hook TEXT NOT NULL,
                    scene_plan_json TEXT NOT NULL,
                    captions_json TEXT NOT NULL,
                    b_roll_json TEXT NOT NULL,
                    audio_direction_json TEXT NOT NULL,
                    hashtags_json TEXT NOT NULL,
                    license_checklist_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_campaign_packs_source_id
                    ON campaign_packs(source_id);

                CREATE INDEX IF NOT EXISTS idx_campaign_packs_clip_idea_id
                    ON campaign_packs(clip_idea_id);

                CREATE TABLE IF NOT EXISTS agent_messages (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    retrieved_context_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_agent_messages_source_id
                    ON agent_messages(source_id);
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

    def save_agent_message(
        self,
        source_id: str,
        role: str,
        content: str,
        retrieved_context: list[str],
    ) -> AgentMessage:
        message_id = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_messages
                    (id, source_id, role, content, retrieved_context_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    source_id,
                    role,
                    content,
                    json.dumps(retrieved_context, ensure_ascii=False),
                ),
            )
        saved = self.get_agent_message(message_id)
        if saved is None:
            raise RuntimeError("Created agent message could not be loaded")
        return saved

    def list_agent_messages(self, source_id: str) -> list[AgentMessage]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, source_id, role, content, retrieved_context_json, created_at
                FROM agent_messages
                WHERE source_id = ?
                ORDER BY created_at ASC
                """,
                (source_id,),
            ).fetchall()
        return [self._agent_message_from_row(row) for row in rows]

    def get_agent_message(self, message_id: str) -> AgentMessage | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, source_id, role, content, retrieved_context_json, created_at
                FROM agent_messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()
        return self._agent_message_from_row(row) if row else None

    def _agent_message_from_row(self, row: sqlite3.Row) -> AgentMessage:
        return AgentMessage(
            id=row["id"],
            source_id=row["source_id"],
            role=row["role"],
            content=row["content"],
            retrieved_context=json.loads(row["retrieved_context_json"]),
            created_at=row["created_at"],
        )

    def save_clip_ideas(self, source_id: str, ideas: list[ClipIdea]) -> list[ClipIdea]:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO clip_ideas (
                    id, source_id, title, hook, summary, platform,
                    duration_seconds, hook_score, audience_angle, cta,
                    platform_fit, source_moments_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        idea.id,
                        source_id,
                        idea.title,
                        idea.hook,
                        idea.summary,
                        idea.platform,
                        idea.duration_seconds,
                        idea.hook_score,
                        idea.audience_angle,
                        idea.cta,
                        idea.platform_fit,
                        json.dumps(idea.source_moments, ensure_ascii=False),
                    )
                    for idea in ideas
                ],
            )
        return ideas

    def list_clip_ideas(self, source_id: str) -> list[ClipIdea]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, hook, summary, platform, duration_seconds,
                    hook_score, audience_angle, cta, platform_fit,
                    source_moments_json
                FROM clip_ideas
                WHERE source_id = ?
                ORDER BY created_at DESC
                """,
                (source_id,),
            ).fetchall()
        return [
            ClipIdea(
                id=row["id"],
                title=row["title"],
                hook=row["hook"],
                summary=row["summary"],
                platform=row["platform"],
                duration_seconds=row["duration_seconds"],
                hook_score=row["hook_score"],
                audience_angle=row["audience_angle"],
                cta=row["cta"],
                platform_fit=row["platform_fit"],
                source_moments=json.loads(row["source_moments_json"]),
            )
            for row in rows
        ]

    def save_campaign_pack(
        self,
        source_id: str,
        clip_idea_id: str,
        pack: ScriptPack,
    ) -> ScriptPack:
        pack_id = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO campaign_packs (
                    id, source_id, clip_idea_id, title, hook, scene_plan_json,
                    captions_json, b_roll_json, audio_direction_json,
                    hashtags_json, license_checklist_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pack_id,
                    source_id,
                    clip_idea_id,
                    pack.title,
                    pack.hook,
                    json.dumps(pack.scene_plan, ensure_ascii=False),
                    json.dumps(pack.captions, ensure_ascii=False),
                    json.dumps(pack.b_roll, ensure_ascii=False),
                    json.dumps(pack.audio_direction, ensure_ascii=False),
                    json.dumps(pack.hashtags, ensure_ascii=False),
                    json.dumps(pack.license_checklist, ensure_ascii=False),
                ),
            )
        saved = self.get_campaign_pack(pack_id)
        if saved is None:
            raise RuntimeError("Created campaign pack could not be loaded")
        return saved

    def list_campaign_packs(
        self,
        source_id: str,
        clip_idea_id: str | None = None,
    ) -> list[ScriptPack]:
        where_clause = "WHERE source_id = ?"
        params: tuple[str, ...] = (source_id,)
        if clip_idea_id:
            where_clause += " AND clip_idea_id = ?"
            params = (source_id, clip_idea_id)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM campaign_packs
                {where_clause}
                ORDER BY created_at DESC
                """,
                params,
            ).fetchall()
        return [self._script_pack_from_row(row) for row in rows]

    def get_campaign_pack(self, pack_id: str) -> ScriptPack | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM campaign_packs
                WHERE id = ?
                """,
                (pack_id,),
            ).fetchone()
        return self._script_pack_from_row(row) if row else None

    def _script_pack_from_row(self, row: sqlite3.Row) -> ScriptPack:
        return ScriptPack(
            id=row["id"],
            source_id=row["source_id"],
            clip_idea_id=row["clip_idea_id"],
            title=row["title"],
            hook=row["hook"],
            scene_plan=json.loads(row["scene_plan_json"]),
            captions=json.loads(row["captions_json"]),
            b_roll=json.loads(row["b_roll_json"]),
            audio_direction=json.loads(row["audio_direction_json"]),
            hashtags=json.loads(row["hashtags_json"]),
            license_checklist=json.loads(row["license_checklist_json"]),
            created_at=row["created_at"],
        )


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
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS clip_ideas (
                        id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                        title TEXT NOT NULL,
                        hook TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        duration_seconds INTEGER NOT NULL,
                        hook_score INTEGER NOT NULL,
                        audience_angle TEXT NOT NULL,
                        cta TEXT NOT NULL,
                        platform_fit TEXT NOT NULL,
                        source_moments_json TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_clip_ideas_source_id
                        ON clip_ideas(source_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS campaign_packs (
                        id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                        clip_idea_id TEXT NOT NULL REFERENCES clip_ideas(id) ON DELETE CASCADE,
                        title TEXT NOT NULL,
                        hook TEXT NOT NULL,
                        scene_plan_json TEXT NOT NULL,
                        captions_json TEXT NOT NULL,
                        b_roll_json TEXT NOT NULL,
                        audio_direction_json TEXT NOT NULL,
                        hashtags_json TEXT NOT NULL,
                        license_checklist_json TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_campaign_packs_source_id
                        ON campaign_packs(source_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_campaign_packs_clip_idea_id
                        ON campaign_packs(clip_idea_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_messages (
                        id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        retrieved_context_json TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_agent_messages_source_id
                        ON agent_messages(source_id)
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

    def save_agent_message(
        self,
        source_id: str,
        role: str,
        content: str,
        retrieved_context: list[str],
    ) -> AgentMessage:
        message_id = str(uuid4())
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO agent_messages
                        (id, source_id, role, content, retrieved_context_json)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        message_id,
                        source_id,
                        role,
                        content,
                        json.dumps(retrieved_context, ensure_ascii=False),
                    ),
                )
        saved = self.get_agent_message(message_id)
        if saved is None:
            raise RuntimeError("Created agent message could not be loaded")
        return saved

    def list_agent_messages(self, source_id: str) -> list[AgentMessage]:
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, source_id, role, content, retrieved_context_json,
                        created_at::text AS created_at
                    FROM agent_messages
                    WHERE source_id = %s
                    ORDER BY created_at ASC
                    """,
                    (source_id,),
                )
                rows = cursor.fetchall()
        return [self._agent_message_from_row(row) for row in rows]

    def get_agent_message(self, message_id: str) -> AgentMessage | None:
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, source_id, role, content, retrieved_context_json,
                        created_at::text AS created_at
                    FROM agent_messages
                    WHERE id = %s
                    """,
                    (message_id,),
                )
                row = cursor.fetchone()
        return self._agent_message_from_row(row) if row else None

    def _agent_message_from_row(self, row: dict[str, Any]) -> AgentMessage:
        return AgentMessage(
            id=row["id"],
            source_id=row["source_id"],
            role=row["role"],
            content=row["content"],
            retrieved_context=json.loads(row["retrieved_context_json"]),
            created_at=row["created_at"],
        )

    def save_clip_ideas(self, source_id: str, ideas: list[ClipIdea]) -> list[ClipIdea]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO clip_ideas (
                        id, source_id, title, hook, summary, platform,
                        duration_seconds, hook_score, audience_angle, cta,
                        platform_fit, source_moments_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        hook = EXCLUDED.hook,
                        summary = EXCLUDED.summary,
                        platform = EXCLUDED.platform,
                        duration_seconds = EXCLUDED.duration_seconds,
                        hook_score = EXCLUDED.hook_score,
                        audience_angle = EXCLUDED.audience_angle,
                        cta = EXCLUDED.cta,
                        platform_fit = EXCLUDED.platform_fit,
                        source_moments_json = EXCLUDED.source_moments_json
                    """,
                    [
                        (
                            idea.id,
                            source_id,
                            idea.title,
                            idea.hook,
                            idea.summary,
                            idea.platform,
                            idea.duration_seconds,
                            idea.hook_score,
                            idea.audience_angle,
                            idea.cta,
                            idea.platform_fit,
                            json.dumps(idea.source_moments, ensure_ascii=False),
                        )
                        for idea in ideas
                    ],
                )
        return ideas

    def list_clip_ideas(self, source_id: str) -> list[ClipIdea]:
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, title, hook, summary, platform, duration_seconds,
                        hook_score, audience_angle, cta, platform_fit,
                        source_moments_json
                    FROM clip_ideas
                    WHERE source_id = %s
                    ORDER BY created_at DESC
                    """,
                    (source_id,),
                )
                rows = cursor.fetchall()
        return [
            ClipIdea(
                id=row["id"],
                title=row["title"],
                hook=row["hook"],
                summary=row["summary"],
                platform=row["platform"],
                duration_seconds=row["duration_seconds"],
                hook_score=row["hook_score"],
                audience_angle=row["audience_angle"],
                cta=row["cta"],
                platform_fit=row["platform_fit"],
                source_moments=json.loads(row["source_moments_json"]),
            )
            for row in rows
        ]

    def save_campaign_pack(
        self,
        source_id: str,
        clip_idea_id: str,
        pack: ScriptPack,
    ) -> ScriptPack:
        pack_id = str(uuid4())
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO campaign_packs (
                        id, source_id, clip_idea_id, title, hook, scene_plan_json,
                        captions_json, b_roll_json, audio_direction_json,
                        hashtags_json, license_checklist_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        pack_id,
                        source_id,
                        clip_idea_id,
                        pack.title,
                        pack.hook,
                        json.dumps(pack.scene_plan, ensure_ascii=False),
                        json.dumps(pack.captions, ensure_ascii=False),
                        json.dumps(pack.b_roll, ensure_ascii=False),
                        json.dumps(pack.audio_direction, ensure_ascii=False),
                        json.dumps(pack.hashtags, ensure_ascii=False),
                        json.dumps(pack.license_checklist, ensure_ascii=False),
                    ),
                )
        saved = self.get_campaign_pack(pack_id)
        if saved is None:
            raise RuntimeError("Created campaign pack could not be loaded")
        return saved

    def list_campaign_packs(
        self,
        source_id: str,
        clip_idea_id: str | None = None,
    ) -> list[ScriptPack]:
        where_clause = "WHERE source_id = %s"
        params: tuple[str, ...] = (source_id,)
        if clip_idea_id:
            where_clause += " AND clip_idea_id = %s"
            params = (source_id, clip_idea_id)
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    f"""
                    SELECT id, source_id, clip_idea_id, title, hook,
                        scene_plan_json, captions_json, b_roll_json,
                        audio_direction_json, hashtags_json,
                        license_checklist_json, created_at::text AS created_at
                    FROM campaign_packs
                    {where_clause}
                    ORDER BY created_at DESC
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [self._script_pack_from_row(row) for row in rows]

    def get_campaign_pack(self, pack_id: str) -> ScriptPack | None:
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, source_id, clip_idea_id, title, hook,
                        scene_plan_json, captions_json, b_roll_json,
                        audio_direction_json, hashtags_json,
                        license_checklist_json, created_at::text AS created_at
                    FROM campaign_packs
                    WHERE id = %s
                    """,
                    (pack_id,),
                )
                row = cursor.fetchone()
        return self._script_pack_from_row(row) if row else None

    def _script_pack_from_row(self, row: dict[str, Any]) -> ScriptPack:
        return ScriptPack(
            id=row["id"],
            source_id=row["source_id"],
            clip_idea_id=row["clip_idea_id"],
            title=row["title"],
            hook=row["hook"],
            scene_plan=json.loads(row["scene_plan_json"]),
            captions=json.loads(row["captions_json"]),
            b_roll=json.loads(row["b_roll_json"]),
            audio_direction=json.loads(row["audio_direction_json"]),
            hashtags=json.loads(row["hashtags_json"]),
            license_checklist=json.loads(row["license_checklist_json"]),
            created_at=row["created_at"],
        )


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
            self.backend = SqliteVectorStore("sqlite:///./data/tasteforge.db")
            self.backend_name = "sqlite-vector"
            self.database_url = "sqlite:///./data/tasteforge.db"

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

    def save_agent_message(
        self,
        source_id: str,
        role: str,
        content: str,
        retrieved_context: list[str],
    ) -> AgentMessage:
        return self.backend.save_agent_message(source_id, role, content, retrieved_context)

    def list_agent_messages(self, source_id: str) -> list[AgentMessage]:
        return self.backend.list_agent_messages(source_id)

    def save_clip_ideas(self, source_id: str, ideas: list[ClipIdea]) -> list[ClipIdea]:
        return self.backend.save_clip_ideas(source_id, ideas)

    def list_clip_ideas(self, source_id: str) -> list[ClipIdea]:
        return self.backend.list_clip_ideas(source_id)

    def save_campaign_pack(
        self,
        source_id: str,
        clip_idea_id: str,
        pack: ScriptPack,
    ) -> ScriptPack:
        return self.backend.save_campaign_pack(source_id, clip_idea_id, pack)

    def list_campaign_packs(
        self,
        source_id: str,
        clip_idea_id: str | None = None,
    ) -> list[ScriptPack]:
        return self.backend.list_campaign_packs(source_id, clip_idea_id)


vector_store = VectorStore()

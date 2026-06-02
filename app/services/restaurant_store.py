from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.schemas import (
    RestaurantCreate,
    RestaurantRecommendation,
    RestaurantResponse,
    TasteAgentMessage,
)

VECTOR_DIMENSIONS = 96


def _embed(text: str) -> list[float]:
    vector = [0.0] * VECTOR_DIMENSIONS
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % VECTOR_DIMENSIONS
        vector[index] += 1.0
    magnitude = math.sqrt(sum(value * value for value in vector))
    return vector if not magnitude else [value / magnitude for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _embedding_to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(str(value) for value in vector) + "]"


def _json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(item) for item in json.loads(value)]


class SqliteRestaurantStore:
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
                CREATE TABLE IF NOT EXISTS restaurants (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    name TEXT NOT NULL,
                    area TEXT NOT NULL,
                    cuisine TEXT NOT NULL,
                    price_level TEXT NOT NULL,
                    mood_tags_json TEXT NOT NULL,
                    signature_menus_json TEXT NOT NULL,
                    kakao_place_id TEXT,
                    kakao_place_url TEXT,
                    address TEXT,
                    road_address TEXT,
                    phone TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_restaurants_user_id
                    ON restaurants(user_id);
                CREATE INDEX IF NOT EXISTS idx_restaurants_area
                    ON restaurants(area);

                CREATE TABLE IF NOT EXISTS restaurant_notes (
                    id TEXT PRIMARY KEY,
                    restaurant_id TEXT NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_restaurant_notes_restaurant_id
                    ON restaurant_notes(restaurant_id);

                CREATE TABLE IF NOT EXISTS taste_agent_messages (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    retrieved_context_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_taste_agent_messages_user_id
                    ON taste_agent_messages(user_id);
                """
            )

    def create_restaurant(self, payload: RestaurantCreate) -> RestaurantResponse:
        restaurant_id = str(uuid4())
        note_id = str(uuid4())
        note_tags = sorted(set(payload.mood_tags + [payload.area, payload.cuisine, payload.price_level]))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO restaurants (
                    id, user_id, name, area, cuisine, price_level, mood_tags_json,
                    signature_menus_json, kakao_place_id, kakao_place_url,
                    address, road_address, phone
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    restaurant_id,
                    payload.user_id,
                    payload.name,
                    payload.area,
                    payload.cuisine,
                    payload.price_level,
                    json.dumps(payload.mood_tags, ensure_ascii=False),
                    json.dumps(payload.signature_menus, ensure_ascii=False),
                    payload.kakao_place_id,
                    payload.kakao_place_url,
                    payload.address,
                    payload.road_address,
                    payload.phone,
                ),
            )
            connection.execute(
                """
                INSERT INTO restaurant_notes
                    (id, restaurant_id, content, tags_json, embedding_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    note_id,
                    restaurant_id,
                    payload.note,
                    json.dumps(note_tags, ensure_ascii=False),
                    json.dumps(_embed(payload.note), ensure_ascii=False),
                ),
            )
        restaurant = self.get_restaurant(restaurant_id)
        if restaurant is None:
            raise RuntimeError("Created restaurant could not be loaded")
        return restaurant

    def list_restaurants(self, user_id: str | None = None) -> list[RestaurantResponse]:
        where_clause = "WHERE restaurants.user_id = ?" if user_id else ""
        params = (user_id,) if user_id else ()
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT restaurants.*, COUNT(restaurant_notes.id) AS note_count
                FROM restaurants
                LEFT JOIN restaurant_notes ON restaurant_notes.restaurant_id = restaurants.id
                {where_clause}
                GROUP BY restaurants.id
                ORDER BY restaurants.created_at DESC
                """,
                params,
            ).fetchall()
        return [self._restaurant_from_row(row) for row in rows]

    def get_restaurant(self, restaurant_id: str) -> RestaurantResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT restaurants.*, COUNT(restaurant_notes.id) AS note_count
                FROM restaurants
                LEFT JOIN restaurant_notes ON restaurant_notes.restaurant_id = restaurants.id
                WHERE restaurants.id = ?
                GROUP BY restaurants.id
                """,
                (restaurant_id,),
            ).fetchone()
        return self._restaurant_from_row(row) if row else None

    def recommend(
        self,
        query: str,
        user_id: str | None,
        area: str | None,
        cuisine: str | None,
        price_level: str | None,
        tags: list[str],
        limit: int,
    ) -> list[RestaurantRecommendation]:
        query_embedding = _embed(" ".join([query, area or "", cuisine or "", price_level or "", " ".join(tags)]))
        rows = self._search_note_rows(user_id, area, cuisine, price_level)
        scored: dict[str, dict[str, Any]] = {}
        normalized_terms = {term.lower() for term in tags + [query, area or "", cuisine or "", price_level or ""] if term}
        for row in rows:
            note_tags = {tag.lower() for tag in _json_list(row["tags_json"])}
            restaurant_tags = {tag.lower() for tag in _json_list(row["mood_tags_json"])}
            vector_score = _cosine(json.loads(row["embedding_json"]), query_embedding)
            tag_score = 0.08 * len(normalized_terms & (note_tags | restaurant_tags))
            keyword_score = 0.05 if any(term and term in row["content"].lower() for term in normalized_terms) else 0.0
            score = vector_score + tag_score + keyword_score
            bucket = scored.setdefault(
                row["id"],
                {
                    "restaurant": self._restaurant_from_row(row),
                    "score": 0.0,
                    "evidence": [],
                },
            )
            bucket["score"] = max(bucket["score"], score)
            if len(bucket["evidence"]) < 2:
                bucket["evidence"].append(row["content"])
        ranked = sorted(scored.values(), key=lambda item: item["score"], reverse=True)
        return [self._recommendation_from_bucket(item) for item in ranked[:limit]]

    def _search_note_rows(
        self,
        user_id: str | None,
        area: str | None,
        cuisine: str | None,
        price_level: str | None,
    ) -> list[sqlite3.Row]:
        clauses = []
        params: list[str] = []
        if user_id:
            clauses.append("restaurants.user_id = ?")
            params.append(user_id)
        if area:
            clauses.append("restaurants.area LIKE ?")
            params.append(f"%{area}%")
        if cuisine:
            clauses.append("restaurants.cuisine LIKE ?")
            params.append(f"%{cuisine}%")
        if price_level:
            clauses.append("restaurants.price_level = ?")
            params.append(price_level)
        where_clause = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            return connection.execute(
                f"""
                SELECT restaurants.*, COUNT(restaurant_notes.id) OVER (PARTITION BY restaurants.id) AS note_count,
                    restaurant_notes.content, restaurant_notes.tags_json, restaurant_notes.embedding_json
                FROM restaurant_notes
                JOIN restaurants ON restaurants.id = restaurant_notes.restaurant_id
                {where_clause}
                """,
                tuple(params),
            ).fetchall()

    def save_message(
        self,
        user_id: str | None,
        role: str,
        content: str,
        retrieved_context: list[str],
    ) -> TasteAgentMessage:
        message_id = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO taste_agent_messages
                    (id, user_id, role, content, retrieved_context_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, user_id, role, content, json.dumps(retrieved_context, ensure_ascii=False)),
            )
            row = connection.execute(
                """
                SELECT id, user_id, role, content, retrieved_context_json, created_at
                FROM taste_agent_messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()
        return self._message_from_row(row)

    def list_messages(self, user_id: str | None) -> list[TasteAgentMessage]:
        where_clause = "WHERE user_id = ?" if user_id else ""
        params = (user_id,) if user_id else ()
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, user_id, role, content, retrieved_context_json, created_at
                FROM taste_agent_messages
                {where_clause}
                ORDER BY created_at ASC
                """,
                params,
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def _restaurant_from_row(self, row: Any) -> RestaurantResponse:
        return RestaurantResponse(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            area=row["area"],
            cuisine=row["cuisine"],
            price_level=row["price_level"],
            mood_tags=_json_list(row["mood_tags_json"]),
            signature_menus=_json_list(row["signature_menus_json"]),
            kakao_place_id=row["kakao_place_id"],
            kakao_place_url=row["kakao_place_url"],
            address=row["address"],
            road_address=row["road_address"],
            phone=row["phone"],
            note_count=int(row["note_count"]),
            created_at=row["created_at"],
        )

    def _recommendation_from_bucket(self, bucket: dict[str, Any]) -> RestaurantRecommendation:
        restaurant: RestaurantResponse = bucket["restaurant"]
        evidence = bucket["evidence"]
        menu_text = ", ".join(restaurant.signature_menus[:2]) if restaurant.signature_menus else "저장된 메모 기준으로 대표 메뉴를 확인해보세요."
        return RestaurantRecommendation(
            restaurant=restaurant,
            reason=f"{restaurant.area}에서 {restaurant.cuisine} 분위기와 요청 조건이 잘 맞는 후보입니다.",
            evidence=evidence,
            menu_tip=f"추천 메뉴: {menu_text}",
            caution="영업시간, 웨이팅, 휴무는 방문 전에 카카오 장소 링크나 매장 공지를 확인하세요.",
            score=round(float(bucket["score"]), 4),
        )

    def _message_from_row(self, row: Any) -> TasteAgentMessage:
        return TasteAgentMessage(
            id=row["id"],
            user_id=row["user_id"],
            role=row["role"],
            content=row["content"],
            retrieved_context=json.loads(row["retrieved_context_json"]),
            created_at=row["created_at"],
        )


class PgRestaurantStore(SqliteRestaurantStore):
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
                    CREATE TABLE IF NOT EXISTS restaurants (
                        id TEXT PRIMARY KEY,
                        user_id TEXT,
                        name TEXT NOT NULL,
                        area TEXT NOT NULL,
                        cuisine TEXT NOT NULL,
                        price_level TEXT NOT NULL,
                        mood_tags_json TEXT NOT NULL,
                        signature_menus_json TEXT NOT NULL,
                        kakao_place_id TEXT,
                        kakao_place_url TEXT,
                        address TEXT,
                        road_address TEXT,
                        phone TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_restaurants_user_id ON restaurants(user_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_restaurants_area ON restaurants(area)")
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS restaurant_notes (
                        id TEXT PRIMARY KEY,
                        restaurant_id TEXT NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
                        content TEXT NOT NULL,
                        tags_json TEXT NOT NULL,
                        embedding VECTOR({VECTOR_DIMENSIONS}) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_restaurant_notes_restaurant_id ON restaurant_notes(restaurant_id)")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS taste_agent_messages (
                        id TEXT PRIMARY KEY,
                        user_id TEXT,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        retrieved_context_json TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_taste_agent_messages_user_id ON taste_agent_messages(user_id)")
                connection.commit()
                try:
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_restaurant_notes_embedding
                            ON restaurant_notes USING hnsw (embedding vector_cosine_ops)
                        """
                    )
                except Exception:
                    connection.rollback()

    def create_restaurant(self, payload: RestaurantCreate) -> RestaurantResponse:
        restaurant_id = str(uuid4())
        note_id = str(uuid4())
        note_tags = sorted(set(payload.mood_tags + [payload.area, payload.cuisine, payload.price_level]))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO restaurants (
                        id, user_id, name, area, cuisine, price_level, mood_tags_json,
                        signature_menus_json, kakao_place_id, kakao_place_url,
                        address, road_address, phone
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        restaurant_id,
                        payload.user_id,
                        payload.name,
                        payload.area,
                        payload.cuisine,
                        payload.price_level,
                        json.dumps(payload.mood_tags, ensure_ascii=False),
                        json.dumps(payload.signature_menus, ensure_ascii=False),
                        payload.kakao_place_id,
                        payload.kakao_place_url,
                        payload.address,
                        payload.road_address,
                        payload.phone,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO restaurant_notes
                        (id, restaurant_id, content, tags_json, embedding)
                    VALUES (%s, %s, %s, %s, %s::vector)
                    """,
                    (
                        note_id,
                        restaurant_id,
                        payload.note,
                        json.dumps(note_tags, ensure_ascii=False),
                        _embedding_to_pgvector(_embed(payload.note)),
                    ),
                )
        restaurant = self.get_restaurant(restaurant_id)
        if restaurant is None:
            raise RuntimeError("Created restaurant could not be loaded")
        return restaurant

    def list_restaurants(self, user_id: str | None = None) -> list[RestaurantResponse]:
        where_clause = "WHERE restaurants.user_id = %s" if user_id else ""
        params = (user_id,) if user_id else ()
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    f"""
                    SELECT restaurants.*, restaurants.created_at::text AS created_at,
                        COUNT(restaurant_notes.id)::int AS note_count
                    FROM restaurants
                    LEFT JOIN restaurant_notes ON restaurant_notes.restaurant_id = restaurants.id
                    {where_clause}
                    GROUP BY restaurants.id
                    ORDER BY restaurants.created_at DESC
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [self._restaurant_from_row(row) for row in rows]

    def get_restaurant(self, restaurant_id: str) -> RestaurantResponse | None:
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT restaurants.*, restaurants.created_at::text AS created_at,
                        COUNT(restaurant_notes.id)::int AS note_count
                    FROM restaurants
                    LEFT JOIN restaurant_notes ON restaurant_notes.restaurant_id = restaurants.id
                    WHERE restaurants.id = %s
                    GROUP BY restaurants.id
                    """,
                    (restaurant_id,),
                )
                row = cursor.fetchone()
        return self._restaurant_from_row(row) if row else None

    def _search_note_rows(
        self,
        user_id: str | None,
        area: str | None,
        cuisine: str | None,
        price_level: str | None,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[str] = []
        if user_id:
            clauses.append("restaurants.user_id = %s")
            params.append(user_id)
        if area:
            clauses.append("restaurants.area ILIKE %s")
            params.append(f"%{area}%")
        if cuisine:
            clauses.append("restaurants.cuisine ILIKE %s")
            params.append(f"%{cuisine}%")
        if price_level:
            clauses.append("restaurants.price_level = %s")
            params.append(price_level)
        where_clause = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    f"""
                    SELECT restaurants.*, restaurants.created_at::text AS created_at,
                        COUNT(restaurant_notes.id) OVER (PARTITION BY restaurants.id)::int AS note_count,
                        restaurant_notes.content, restaurant_notes.tags_json,
                        restaurant_notes.embedding::text AS embedding_json
                    FROM restaurant_notes
                    JOIN restaurants ON restaurants.id = restaurant_notes.restaurant_id
                    {where_clause}
                    """,
                    tuple(params),
                )
                return list(cursor.fetchall())

    def save_message(
        self,
        user_id: str | None,
        role: str,
        content: str,
        retrieved_context: list[str],
    ) -> TasteAgentMessage:
        message_id = str(uuid4())
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO taste_agent_messages
                        (id, user_id, role, content, retrieved_context_json)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (message_id, user_id, role, content, json.dumps(retrieved_context, ensure_ascii=False)),
                )
                cursor.execute(
                    """
                    SELECT id, user_id, role, content, retrieved_context_json,
                        created_at::text AS created_at
                    FROM taste_agent_messages
                    WHERE id = %s
                    """,
                    (message_id,),
                )
                row = cursor.fetchone()
        return self._message_from_row(row)

    def list_messages(self, user_id: str | None) -> list[TasteAgentMessage]:
        where_clause = "WHERE user_id = %s" if user_id else ""
        params = (user_id,) if user_id else ()
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    f"""
                    SELECT id, user_id, role, content, retrieved_context_json,
                        created_at::text AS created_at
                    FROM taste_agent_messages
                    {where_clause}
                    ORDER BY created_at ASC
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [self._message_from_row(row) for row in rows]


class RestaurantStore:
    def __init__(self) -> None:
        try:
            if settings.database_url.startswith(("postgresql://", "postgres://")):
                self.backend = PgRestaurantStore(settings.database_url)
            elif settings.database_url.startswith("sqlite:///"):
                self.backend = SqliteRestaurantStore(settings.database_url)
            else:
                raise ValueError("Unsupported DATABASE_URL")
        except Exception:
            self.backend = SqliteRestaurantStore("sqlite:///./data/tasteforge.db")

    def create_restaurant(self, payload: RestaurantCreate) -> RestaurantResponse:
        return self.backend.create_restaurant(payload)

    def list_restaurants(self, user_id: str | None = None) -> list[RestaurantResponse]:
        return self.backend.list_restaurants(user_id)

    def get_restaurant(self, restaurant_id: str) -> RestaurantResponse | None:
        return self.backend.get_restaurant(restaurant_id)

    def recommend(
        self,
        query: str,
        user_id: str | None,
        area: str | None,
        cuisine: str | None,
        price_level: str | None,
        tags: list[str],
        limit: int,
    ) -> list[RestaurantRecommendation]:
        return self.backend.recommend(query, user_id, area, cuisine, price_level, tags, limit)

    def save_message(
        self,
        user_id: str | None,
        role: str,
        content: str,
        retrieved_context: list[str],
    ) -> TasteAgentMessage:
        return self.backend.save_message(user_id, role, content, retrieved_context)

    def list_messages(self, user_id: str | None) -> list[TasteAgentMessage]:
        return self.backend.list_messages(user_id)


restaurant_store = RestaurantStore()

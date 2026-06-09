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
    RestaurantNoteCreate,
    RestaurantRecommendation,
    RestaurantResponse,
    RestaurantUpdate,
    TasteAgentMessage,
    TasteAgentSession,
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


def _distance_km(
    left_latitude: float | None,
    left_longitude: float | None,
    right_latitude: float | None,
    right_longitude: float | None,
) -> float | None:
    if None in (left_latitude, left_longitude, right_latitude, right_longitude):
        return None
    earth_radius_km = 6371.0
    lat1 = math.radians(float(left_latitude))
    lat2 = math.radians(float(right_latitude))
    delta_lat = math.radians(float(right_latitude) - float(left_latitude))
    delta_lon = math.radians(float(right_longitude) - float(left_longitude))
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return earth_radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


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
        database_path = Path(database_url.removeprefix("sqlite:///")).resolve()
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
                    city TEXT,
                    district TEXT,
                    town TEXT,
                    cuisine TEXT NOT NULL,
                    price_level TEXT NOT NULL,
                    mood_tags_json TEXT NOT NULL,
                    signature_menus_json TEXT NOT NULL,
                    kakao_place_id TEXT,
                    kakao_place_url TEXT,
                    address TEXT,
                    road_address TEXT,
                    phone TEXT,
                    latitude REAL,
                    longitude REAL,
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

                CREATE TABLE IF NOT EXISTS taste_agent_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_taste_agent_sessions_user_id
                    ON taste_agent_sessions(user_id);

                CREATE TABLE IF NOT EXISTS taste_agent_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT REFERENCES taste_agent_sessions(id) ON DELETE CASCADE,
                    user_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    retrieved_context_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_taste_agent_messages_user_id
                    ON taste_agent_messages(user_id);

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
                """
            )
            for statement in (
                "ALTER TABLE restaurants ADD COLUMN latitude REAL",
                "ALTER TABLE restaurants ADD COLUMN longitude REAL",
                "ALTER TABLE restaurants ADD COLUMN city TEXT",
                "ALTER TABLE restaurants ADD COLUMN district TEXT",
                "ALTER TABLE restaurants ADD COLUMN town TEXT",
                "ALTER TABLE taste_agent_messages ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
                "ALTER TABLE taste_agent_messages ADD COLUMN session_id TEXT REFERENCES taste_agent_sessions(id) ON DELETE CASCADE",
            ):
                try:
                    connection.execute(statement)
                except sqlite3.OperationalError:
                    pass

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

    def upsert_user(
        self,
        email: str,
        display_name: str,
        avatar_url: str | None,
        auth_provider: str,
        provider_subject: str,
    ) -> dict[str, Any]:
        existing = self.get_user_by_provider(auth_provider, provider_subject)
        if existing is None:
            return self.create_user(email, display_name, avatar_url, auth_provider, provider_subject)

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE users
                SET email = ?, display_name = ?, avatar_url = ?, last_login_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (email, display_name, avatar_url, existing["id"]),
            )
        user = self.get_user(existing["id"])
        if user is None:
            raise RuntimeError("Updated user could not be loaded")
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

    def get_user_by_provider(self, auth_provider: str, provider_subject: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, email, display_name, avatar_url, auth_provider,
                    provider_subject, created_at, last_login_at
                FROM users
                WHERE auth_provider = ? AND provider_subject = ?
                """,
                (auth_provider, provider_subject),
            ).fetchone()
        return dict(row) if row else None

    def create_restaurant(self, payload: RestaurantCreate) -> RestaurantResponse:
        restaurant_id = str(uuid4())
        note_id = str(uuid4())
        note_tags = sorted(set(payload.mood_tags + [payload.area, payload.cuisine, payload.price_level]))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO restaurants (
                    id, user_id, name, area, city, district, town, cuisine, price_level, mood_tags_json,
                    signature_menus_json, kakao_place_id, kakao_place_url,
                    address, road_address, phone, latitude, longitude
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    restaurant_id,
                    payload.user_id,
                    payload.name,
                    payload.area,
                    payload.city,
                    payload.district,
                    payload.town,
                    payload.cuisine,
                    payload.price_level,
                    json.dumps(payload.mood_tags, ensure_ascii=False),
                    json.dumps(payload.signature_menus, ensure_ascii=False),
                    payload.kakao_place_id,
                    payload.kakao_place_url,
                    payload.address,
                    payload.road_address,
                    payload.phone,
                    payload.latitude,
                    payload.longitude,
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

    def add_note(self, restaurant_id: str, payload: RestaurantNoteCreate) -> RestaurantResponse | None:
        restaurant = self.get_restaurant(restaurant_id)
        if restaurant is None:
            return None
        note_id = str(uuid4())
        note_tags = sorted(set(payload.tags + restaurant.mood_tags + [restaurant.area, restaurant.cuisine, restaurant.price_level]))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO restaurant_notes
                    (id, restaurant_id, content, tags_json, embedding_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    note_id,
                    restaurant_id,
                    payload.content,
                    json.dumps(note_tags, ensure_ascii=False),
                    json.dumps(_embed(payload.content), ensure_ascii=False),
                ),
            )
        return self.get_restaurant(restaurant_id)

    def list_restaurants(
        self,
        user_id: str | None = None,
        city: str | None = None,
        district: str | None = None,
        town: str | None = None,
    ) -> list[RestaurantResponse]:
        clauses = []
        params: list[str] = []
        if user_id:
            clauses.append("restaurants.user_id = ?")
            params.append(user_id)
        for value in (city, district, town):
            if value:
                clauses.append(
                    """(
                        restaurants.city LIKE ?
                        OR restaurants.district LIKE ?
                        OR restaurants.town LIKE ?
                        OR restaurants.road_address LIKE ?
                        OR restaurants.address LIKE ?
                        OR restaurants.area LIKE ?
                    )"""
                )
                params.extend([f"%{value}%", f"%{value}%", f"%{value}%", f"%{value}%", f"%{value}%", f"%{value}%"])
        where_clause = "WHERE " + " AND ".join(clauses) if clauses else ""
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
                tuple(params),
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

    def update_restaurant(self, restaurant_id: str, payload: RestaurantUpdate) -> RestaurantResponse | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE restaurants
                SET name = ?,
                    area = ?,
                    city = ?,
                    district = ?,
                    town = ?,
                    cuisine = ?,
                    price_level = ?,
                    mood_tags_json = ?,
                    kakao_place_id = ?,
                    kakao_place_url = ?,
                    address = ?,
                    road_address = ?,
                    phone = ?,
                    latitude = ?,
                    longitude = ?
                WHERE id = ?
                """,
                (
                    payload.name,
                    payload.area,
                    payload.city,
                    payload.district,
                    payload.town,
                    payload.cuisine,
                    payload.price_level,
                    json.dumps(payload.mood_tags, ensure_ascii=False),
                    payload.kakao_place_id,
                    payload.kakao_place_url,
                    payload.address,
                    payload.road_address,
                    payload.phone,
                    payload.latitude,
                    payload.longitude,
                    restaurant_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_restaurant(restaurant_id)

    def delete_restaurant(self, restaurant_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("DELETE FROM restaurant_notes WHERE restaurant_id = ?", (restaurant_id,))
            cursor = connection.execute("DELETE FROM restaurants WHERE id = ?", (restaurant_id,))
            return cursor.rowcount > 0

    def recommend(
        self,
        query: str,
        user_id: str | None,
        area: str | None,
        cuisine: str | None,
        price_level: str | None,
        tags: list[str],
        latitude: float | None,
        longitude: float | None,
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
            distance = _distance_km(latitude, longitude, row["latitude"], row["longitude"])
            distance_score = 0.0 if distance is None else max(0.0, 0.18 - min(distance, 10.0) * 0.018)
            score = vector_score + tag_score + keyword_score + distance_score
            bucket = scored.setdefault(
                row["id"],
                {
                    "restaurant": self._restaurant_from_row(row),
                    "score": 0.0,
                    "evidence": [],
                    "distance_km": distance,
                },
            )
            bucket["score"] = max(bucket["score"], score)
            if distance is not None:
                bucket["distance_km"] = distance
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
        session_id: str,
        user_id: str | None,
        role: str,
        content: str,
        retrieved_context: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> TasteAgentMessage:
        message_id = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO taste_agent_messages
                    (id, session_id, user_id, role, content, retrieved_context_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    user_id,
                    role,
                    content,
                    json.dumps(retrieved_context, ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            row = connection.execute(
                """
                SELECT id, session_id, user_id, role, content, retrieved_context_json, metadata_json, created_at
                FROM taste_agent_messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()
        return self._message_from_row(row)

    def create_chat_session(self, user_id: str | None, title: str) -> TasteAgentSession:
        session_id = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO taste_agent_sessions (id, user_id, title)
                VALUES (?, ?, ?)
                """,
                (session_id, user_id, title[:80] or "새 대화"),
            )
        return TasteAgentSession(
            id=session_id,
            user_id=user_id,
            title=title[:80] or "새 대화",
            created_at="",
            updated_at="",
            messages=[],
        )

    def ensure_chat_session(self, user_id: str | None, session_id: str | None, title: str) -> str:
        if session_id:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT id FROM taste_agent_sessions WHERE id = ? AND user_id = ?",
                    (session_id, user_id),
                ).fetchone()
            if row:
                return str(row["id"])

        session = self.create_chat_session(user_id, title)
        return session.id

    def touch_chat_session(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE taste_agent_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,),
            )

    def list_messages(self, user_id: str | None) -> list[TasteAgentMessage]:
        where_clause = "WHERE user_id = ?" if user_id else ""
        params = (user_id,) if user_id else ()
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, session_id, user_id, role, content, retrieved_context_json, metadata_json, created_at
                FROM taste_agent_messages
                {where_clause}
                ORDER BY created_at ASC
                """,
                params,
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def list_sessions(self, user_id: str | None) -> list[TasteAgentSession]:
        messages = self.list_messages(user_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, title, created_at, updated_at
                FROM taste_agent_sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()

        grouped: dict[str, list[TasteAgentMessage]] = {}
        legacy_messages: list[TasteAgentMessage] = []
        for message in messages:
            if message.session_id:
                grouped.setdefault(message.session_id, []).append(message)
            else:
                legacy_messages.append(message)

        sessions = [
            TasteAgentSession(
                id=row["id"],
                user_id=row["user_id"],
                title=row["title"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                messages=grouped.get(row["id"], []),
            )
            for row in rows
        ]
        if legacy_messages:
            sessions.append(
                TasteAgentSession(
                    id="legacy",
                    user_id=user_id,
                    title="이전 대화 기록",
                    created_at=legacy_messages[0].created_at,
                    updated_at=legacy_messages[-1].created_at,
                    messages=legacy_messages,
                )
            )
        return sessions

    def _restaurant_from_row(self, row: Any) -> RestaurantResponse:
        return RestaurantResponse(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            area=row["area"],
            city=row["city"],
            district=row["district"],
            town=row["town"],
            cuisine=row["cuisine"],
            price_level=row["price_level"],
            mood_tags=_json_list(row["mood_tags_json"]),
            signature_menus=_json_list(row["signature_menus_json"]),
            kakao_place_id=row["kakao_place_id"],
            kakao_place_url=row["kakao_place_url"],
            address=row["address"],
            road_address=row["road_address"],
            phone=row["phone"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            note_count=int(row["note_count"]),
            created_at=row["created_at"],
        )

    def _recommendation_from_bucket(self, bucket: dict[str, Any]) -> RestaurantRecommendation:
        restaurant: RestaurantResponse = bucket["restaurant"]
        evidence = bucket["evidence"]
        review_point = evidence[0] if evidence else "저장된 리뷰를 기준으로 분위기와 취향을 확인해보세요."
        distance = bucket.get("distance_km")
        location_hint = f" 현재 위치에서 약 {distance:.1f}km 거리입니다." if distance is not None else ""
        return RestaurantRecommendation(
            restaurant=restaurant,
            reason=f"{restaurant.area}에서 {restaurant.cuisine} 분위기와 요청 조건이 잘 맞는 후보입니다.{location_hint}",
            evidence=evidence,
            menu_tip=f"추천 포인트: {review_point}",
            caution="영업시간, 웨이팅, 휴무는 방문 전에 카카오 장소 링크나 매장 공지를 확인하세요.",
            score=round(float(bucket["score"]), 4),
        )

    def _message_from_row(self, row: Any) -> TasteAgentMessage:
        return TasteAgentMessage(
            id=row["id"],
            session_id=row["session_id"] if "session_id" in row.keys() else None,
            user_id=row["user_id"],
            role=row["role"],
            content=row["content"],
            retrieved_context=json.loads(row["retrieved_context_json"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
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
                        city TEXT,
                        district TEXT,
                        town TEXT,
                        cuisine TEXT NOT NULL,
                        price_level TEXT NOT NULL,
                        mood_tags_json TEXT NOT NULL,
                        signature_menus_json TEXT NOT NULL,
                        kakao_place_id TEXT,
                        kakao_place_url TEXT,
                        address TEXT,
                        road_address TEXT,
                        phone TEXT,
                        latitude DOUBLE PRECISION,
                        longitude DOUBLE PRECISION,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION")
                cursor.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION")
                cursor.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS city TEXT")
                cursor.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS district TEXT")
                cursor.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS town TEXT")
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
                    CREATE TABLE IF NOT EXISTS taste_agent_sessions (
                        id TEXT PRIMARY KEY,
                        user_id TEXT,
                        title TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_taste_agent_sessions_user_id ON taste_agent_sessions(user_id)")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS taste_agent_messages (
                        id TEXT PRIMARY KEY,
                        session_id TEXT REFERENCES taste_agent_sessions(id) ON DELETE CASCADE,
                        user_id TEXT,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        retrieved_context_json TEXT NOT NULL,
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_taste_agent_messages_user_id ON taste_agent_messages(user_id)")
                cursor.execute("ALTER TABLE taste_agent_messages ADD COLUMN IF NOT EXISTS metadata_json TEXT NOT NULL DEFAULT '{}'")
                cursor.execute("ALTER TABLE taste_agent_messages ADD COLUMN IF NOT EXISTS session_id TEXT REFERENCES taste_agent_sessions(id) ON DELETE CASCADE")
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
                        id, user_id, name, area, city, district, town, cuisine, price_level, mood_tags_json,
                        signature_menus_json, kakao_place_id, kakao_place_url,
                        address, road_address, phone, latitude, longitude
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        restaurant_id,
                        payload.user_id,
                        payload.name,
                        payload.area,
                        payload.city,
                        payload.district,
                        payload.town,
                        payload.cuisine,
                        payload.price_level,
                        json.dumps(payload.mood_tags, ensure_ascii=False),
                        json.dumps(payload.signature_menus, ensure_ascii=False),
                        payload.kakao_place_id,
                        payload.kakao_place_url,
                        payload.address,
                        payload.road_address,
                        payload.phone,
                        payload.latitude,
                        payload.longitude,
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

    def add_note(self, restaurant_id: str, payload: RestaurantNoteCreate) -> RestaurantResponse | None:
        restaurant = self.get_restaurant(restaurant_id)
        if restaurant is None:
            return None
        note_id = str(uuid4())
        note_tags = sorted(set(payload.tags + restaurant.mood_tags + [restaurant.area, restaurant.cuisine, restaurant.price_level]))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO restaurant_notes
                        (id, restaurant_id, content, tags_json, embedding)
                    VALUES (%s, %s, %s, %s, %s::vector)
                    """,
                    (
                        note_id,
                        restaurant_id,
                        payload.content,
                        json.dumps(note_tags, ensure_ascii=False),
                        _embedding_to_pgvector(_embed(payload.content)),
                    ),
                )
        return self.get_restaurant(restaurant_id)

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

    def upsert_user(
        self,
        email: str,
        display_name: str,
        avatar_url: str | None,
        auth_provider: str,
        provider_subject: str,
    ) -> dict[str, Any]:
        existing = self.get_user_by_provider(auth_provider, provider_subject)
        if existing is None:
            return self.create_user(email, display_name, avatar_url, auth_provider, provider_subject)

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET email = %s, display_name = %s, avatar_url = %s, last_login_at = NOW()
                    WHERE id = %s
                    """,
                    (email, display_name, avatar_url, existing["id"]),
                )
        user = self.get_user(existing["id"])
        if user is None:
            raise RuntimeError("Updated user could not be loaded")
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

    def get_user_by_provider(self, auth_provider: str, provider_subject: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, email, display_name, avatar_url, auth_provider,
                        provider_subject, created_at::text AS created_at,
                        last_login_at::text AS last_login_at
                    FROM users
                    WHERE auth_provider = %s AND provider_subject = %s
                    """,
                    (auth_provider, provider_subject),
                )
                return cursor.fetchone()

    def list_restaurants(
        self,
        user_id: str | None = None,
        city: str | None = None,
        district: str | None = None,
        town: str | None = None,
    ) -> list[RestaurantResponse]:
        clauses = []
        params: list[str] = []
        if user_id:
            clauses.append("restaurants.user_id = %s")
            params.append(user_id)
        for value in (city, district, town):
            if value:
                clauses.append(
                    """(
                        restaurants.city ILIKE %s
                        OR restaurants.district ILIKE %s
                        OR restaurants.town ILIKE %s
                        OR restaurants.road_address ILIKE %s
                        OR restaurants.address ILIKE %s
                        OR restaurants.area ILIKE %s
                    )"""
                )
                params.extend([f"%{value}%", f"%{value}%", f"%{value}%", f"%{value}%", f"%{value}%", f"%{value}%"])
        where_clause = "WHERE " + " AND ".join(clauses) if clauses else ""
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
                    tuple(params),
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

    def update_restaurant(self, restaurant_id: str, payload: RestaurantUpdate) -> RestaurantResponse | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE restaurants
                    SET name = %s,
                        area = %s,
                        city = %s,
                        district = %s,
                        town = %s,
                        cuisine = %s,
                        price_level = %s,
                        mood_tags_json = %s,
                        kakao_place_id = %s,
                        kakao_place_url = %s,
                        address = %s,
                        road_address = %s,
                        phone = %s,
                        latitude = %s,
                        longitude = %s
                    WHERE id = %s
                    """,
                    (
                        payload.name,
                        payload.area,
                        payload.city,
                        payload.district,
                        payload.town,
                        payload.cuisine,
                        payload.price_level,
                        json.dumps(payload.mood_tags, ensure_ascii=False),
                        payload.kakao_place_id,
                        payload.kakao_place_url,
                        payload.address,
                        payload.road_address,
                        payload.phone,
                        payload.latitude,
                        payload.longitude,
                        restaurant_id,
                    ),
                )
                updated = cursor.rowcount > 0
            connection.commit()
        return self.get_restaurant(restaurant_id) if updated else None

    def delete_restaurant(self, restaurant_id: str) -> bool:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM restaurant_notes WHERE restaurant_id = %s", (restaurant_id,))
                cursor.execute("DELETE FROM restaurants WHERE id = %s", (restaurant_id,))
                deleted = cursor.rowcount > 0
            connection.commit()
        return deleted

    def recommend(
        self,
        query: str,
        user_id: str | None,
        area: str | None,
        cuisine: str | None,
        price_level: str | None,
        tags: list[str],
        latitude: float | None,
        longitude: float | None,
        limit: int,
    ) -> list[RestaurantRecommendation]:
        query_text = " ".join([query, area or "", cuisine or "", price_level or "", " ".join(tags)])
        query_embedding = _embedding_to_pgvector(_embed(query_text))
        rows = self._search_vector_note_rows(query_embedding, user_id, area, cuisine, price_level, limit * 8)
        scored: dict[str, dict[str, Any]] = {}
        normalized_terms = {term.lower() for term in tags + [query, area or "", cuisine or "", price_level or ""] if term}
        for row in rows:
            note_tags = {tag.lower() for tag in _json_list(row["tags_json"])}
            restaurant_tags = {tag.lower() for tag in _json_list(row["mood_tags_json"])}
            vector_score = float(row["vector_score"])
            tag_score = 0.08 * len(normalized_terms & (note_tags | restaurant_tags))
            keyword_score = 0.05 if any(term and term in row["content"].lower() for term in normalized_terms) else 0.0
            distance = _distance_km(latitude, longitude, row["latitude"], row["longitude"])
            distance_score = 0.0 if distance is None else max(0.0, 0.18 - min(distance, 10.0) * 0.018)
            score = vector_score + tag_score + keyword_score + distance_score
            bucket = scored.setdefault(
                row["id"],
                {
                    "restaurant": self._restaurant_from_row(row),
                    "score": 0.0,
                    "evidence": [],
                    "distance_km": distance,
                },
            )
            bucket["score"] = max(bucket["score"], score)
            if distance is not None:
                bucket["distance_km"] = distance
            if len(bucket["evidence"]) < 2:
                bucket["evidence"].append(row["content"])
        ranked = sorted(scored.values(), key=lambda item: item["score"], reverse=True)
        return [self._recommendation_from_bucket(item) for item in ranked[:limit]]

    def _search_vector_note_rows(
        self,
        query_embedding: str,
        user_id: str | None,
        area: str | None,
        cuisine: str | None,
        price_level: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = [query_embedding]
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
        params.append(max(limit, 1))
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    f"""
                    WITH query_embedding AS (SELECT %s::vector AS embedding)
                    SELECT restaurants.*, restaurants.created_at::text AS created_at,
                        COUNT(restaurant_notes.id) OVER (PARTITION BY restaurants.id)::int AS note_count,
                        restaurant_notes.content, restaurant_notes.tags_json,
                        1 - (restaurant_notes.embedding <=> query_embedding.embedding) AS vector_score
                    FROM restaurant_notes
                    JOIN restaurants ON restaurants.id = restaurant_notes.restaurant_id
                    CROSS JOIN query_embedding
                    {where_clause}
                    ORDER BY restaurant_notes.embedding <=> query_embedding.embedding
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return list(cursor.fetchall())

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
        session_id: str,
        user_id: str | None,
        role: str,
        content: str,
        retrieved_context: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> TasteAgentMessage:
        message_id = str(uuid4())
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO taste_agent_messages
                        (id, session_id, user_id, role, content, retrieved_context_json, metadata_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        message_id,
                        session_id,
                        user_id,
                        role,
                        content,
                        json.dumps(retrieved_context, ensure_ascii=False),
                        json.dumps(metadata or {}, ensure_ascii=False),
                    ),
                )
                cursor.execute(
                    """
                    SELECT id, session_id, user_id, role, content, retrieved_context_json, metadata_json,
                        created_at::text AS created_at
                    FROM taste_agent_messages
                    WHERE id = %s
                    """,
                    (message_id,),
                )
                row = cursor.fetchone()
        return self._message_from_row(row)

    def create_chat_session(self, user_id: str | None, title: str) -> TasteAgentSession:
        session_id = str(uuid4())
        session_title = title[:80] or "새 대화"
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO taste_agent_sessions (id, user_id, title)
                    VALUES (%s, %s, %s)
                    """,
                    (session_id, user_id, session_title),
                )
                connection.commit()
                cursor.execute(
                    """
                    SELECT id, user_id, title, created_at::text AS created_at, updated_at::text AS updated_at
                    FROM taste_agent_sessions
                    WHERE id = %s
                    """,
                    (session_id,),
                )
                row = cursor.fetchone()
        return TasteAgentSession(**row, messages=[])

    def ensure_chat_session(self, user_id: str | None, session_id: str | None, title: str) -> str:
        if session_id:
            with self._connect() as connection:
                with connection.cursor(row_factory=self.dict_row) as cursor:
                    cursor.execute(
                        "SELECT id FROM taste_agent_sessions WHERE id = %s AND user_id = %s",
                        (session_id, user_id),
                    )
                    row = cursor.fetchone()
            if row:
                return str(row["id"])
        return self.create_chat_session(user_id, title).id

    def touch_chat_session(self, session_id: str) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE taste_agent_sessions SET updated_at = NOW() WHERE id = %s",
                    (session_id,),
                )
            connection.commit()

    def list_messages(self, user_id: str | None) -> list[TasteAgentMessage]:
        where_clause = "WHERE user_id = %s" if user_id else ""
        params = (user_id,) if user_id else ()
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    f"""
                    SELECT id, session_id, user_id, role, content, retrieved_context_json, metadata_json,
                        created_at::text AS created_at
                    FROM taste_agent_messages
                    {where_clause}
                    ORDER BY created_at ASC
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [self._message_from_row(row) for row in rows]

    def list_sessions(self, user_id: str | None) -> list[TasteAgentSession]:
        messages = self.list_messages(user_id)
        with self._connect() as connection:
            with connection.cursor(row_factory=self.dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, title, created_at::text AS created_at, updated_at::text AS updated_at
                    FROM taste_agent_sessions
                    WHERE user_id = %s
                    ORDER BY updated_at DESC
                    """,
                    (user_id,),
                )
                rows = cursor.fetchall()

        grouped: dict[str, list[TasteAgentMessage]] = {}
        legacy_messages: list[TasteAgentMessage] = []
        for message in messages:
            if message.session_id:
                grouped.setdefault(message.session_id, []).append(message)
            else:
                legacy_messages.append(message)

        sessions = [
            TasteAgentSession(
                id=row["id"],
                user_id=row["user_id"],
                title=row["title"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                messages=grouped.get(row["id"], []),
            )
            for row in rows
        ]
        if legacy_messages:
            sessions.append(
                TasteAgentSession(
                    id="legacy",
                    user_id=user_id,
                    title="이전 대화 기록",
                    created_at=legacy_messages[0].created_at,
                    updated_at=legacy_messages[-1].created_at,
                    messages=legacy_messages,
                )
            )
        return sessions


class RestaurantStore:
    def __init__(self) -> None:
        self.initialization_error: str | None = None
        try:
            if settings.database_url.startswith(("postgresql://", "postgres://")):
                self.backend = PgRestaurantStore(settings.database_url)
                self.backend_name = "pgvector"
            elif settings.database_url.startswith("sqlite:///"):
                self.backend = SqliteRestaurantStore(settings.database_url)
                self.backend_name = "sqlite-vector"
            else:
                raise ValueError("Unsupported DATABASE_URL")
        except Exception as error:
            self.initialization_error = str(error)
            self.backend = SqliteRestaurantStore("sqlite:///./data/nyambot.db")
            self.backend_name = "sqlite-vector"

    def create_restaurant(self, payload: RestaurantCreate) -> RestaurantResponse:
        return self.backend.create_restaurant(payload)

    def add_note(self, restaurant_id: str, payload: RestaurantNoteCreate) -> RestaurantResponse | None:
        return self.backend.add_note(restaurant_id, payload)

    def create_user(
        self,
        email: str,
        display_name: str,
        avatar_url: str | None,
        auth_provider: str,
        provider_subject: str | None,
    ) -> dict[str, Any]:
        return self.backend.create_user(email, display_name, avatar_url, auth_provider, provider_subject)

    def upsert_user(
        self,
        email: str,
        display_name: str,
        avatar_url: str | None,
        auth_provider: str,
        provider_subject: str,
    ) -> dict[str, Any]:
        return self.backend.upsert_user(email, display_name, avatar_url, auth_provider, provider_subject)

    def list_users(self) -> list[dict[str, Any]]:
        return self.backend.list_users()

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self.backend.get_user(user_id)

    def get_user_by_provider(self, auth_provider: str, provider_subject: str) -> dict[str, Any] | None:
        return self.backend.get_user_by_provider(auth_provider, provider_subject)

    def list_restaurants(
        self,
        user_id: str | None = None,
        city: str | None = None,
        district: str | None = None,
        town: str | None = None,
    ) -> list[RestaurantResponse]:
        return self.backend.list_restaurants(user_id, city, district, town)

    def get_restaurant(self, restaurant_id: str) -> RestaurantResponse | None:
        return self.backend.get_restaurant(restaurant_id)

    def update_restaurant(self, restaurant_id: str, payload: RestaurantUpdate) -> RestaurantResponse | None:
        return self.backend.update_restaurant(restaurant_id, payload)

    def delete_restaurant(self, restaurant_id: str) -> bool:
        return self.backend.delete_restaurant(restaurant_id)

    def recommend(
        self,
        query: str,
        user_id: str | None,
        area: str | None,
        cuisine: str | None,
        price_level: str | None,
        tags: list[str],
        latitude: float | None,
        longitude: float | None,
        limit: int,
    ) -> list[RestaurantRecommendation]:
        return self.backend.recommend(query, user_id, area, cuisine, price_level, tags, latitude, longitude, limit)

    def save_message(
        self,
        session_id: str,
        user_id: str | None,
        role: str,
        content: str,
        retrieved_context: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> TasteAgentMessage:
        return self.backend.save_message(session_id, user_id, role, content, retrieved_context, metadata)

    def list_messages(self, user_id: str | None) -> list[TasteAgentMessage]:
        return self.backend.list_messages(user_id)

    def ensure_chat_session(self, user_id: str | None, session_id: str | None, title: str) -> str:
        return self.backend.ensure_chat_session(user_id, session_id, title)

    def touch_chat_session(self, session_id: str) -> None:
        self.backend.touch_chat_session(session_id)

    def list_sessions(self, user_id: str | None) -> list[TasteAgentSession]:
        return self.backend.list_sessions(user_id)


restaurant_store = RestaurantStore()

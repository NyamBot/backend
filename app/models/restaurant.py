from dataclasses import dataclass, field


@dataclass(frozen=True)
class Restaurant:
    """Domain model for restaurant data.

    현재는 SQLAlchemy ORM Entity가 아니라, Spring의 Entity 개념을 설명하기 위한
    도메인 모델이다. API 입출력 검증은 schemas.py의 Pydantic DTO가 담당한다.
    """

    id: str
    user_id: str | None
    name: str
    area: str
    city: str | None
    district: str | None
    town: str | None
    cuisine: str
    price_level: str
    mood_tags: list[str] = field(default_factory=list)
    signature_menus: list[str] = field(default_factory=list)
    kakao_place_id: str | None = None
    kakao_place_url: str | None = None
    address: str | None = None
    road_address: str | None = None
    phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class RestaurantNote:
    """Domain model for the text that is embedded and searched by vector similarity."""

    id: str
    restaurant_id: str
    content: str
    tags: list[str] = field(default_factory=list)
    embedding: list[float] = field(default_factory=list)
    created_at: str | None = None

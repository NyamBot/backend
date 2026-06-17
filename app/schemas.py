from typing import Any

from pydantic import BaseModel, Field

TextFilter = str | list[str] | None


class HealthResponse(BaseModel):
    status: str
    app: str
    vector_store: str
    chat_message_store: str
    chat_message_error: str | None = None


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    display_name: str = Field(min_length=1, max_length=120)
    avatar_url: str | None = None
    auth_provider: str = "demo"
    provider_subject: str | None = None


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: str | None
    auth_provider: str
    provider_subject: str | None
    role: str = "user"
    level_points: int = 0
    level_key: str = "egg"
    level_label: str = "알"
    created_at: str
    last_login_at: str | None


class UserLevelResponse(BaseModel):
    user_id: str
    level_points: int
    level_key: str
    level_label: str
    current_level_min_points: int
    next_level_key: str | None
    next_level_label: str | None
    next_level_min_points: int | None
    points_to_next_level: int | None


class UserLevelEventRequest(BaseModel):
    event_type: str = Field(
        description=(
            "Supported events: restaurant_saved, restaurant_shared, quality_note, "
            "like_received, saved_by_other, weekly_share"
        )
    )


class UserLevelEventResponse(BaseModel):
    event_type: str
    points_added: int
    level: UserLevelResponse


class AuthCallbackResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class AuthCodeExchangeRequest(BaseModel):
    code: str = Field(min_length=1)


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RestaurantCreate(BaseModel):
    user_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    area: str = Field(min_length=1, max_length=80)
    city: str | None = None
    district: str | None = None
    town: str | None = None
    cuisine: str = Field(min_length=1, max_length=80)
    price_level: str = "1~2만원"
    mood_tags: list[str] = []
    signature_menus: list[str] = []
    note: str = Field(min_length=10)
    kakao_place_id: str | None = None
    kakao_place_url: str | None = None
    address: str | None = None
    road_address: str | None = None
    phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class RestaurantUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    area: str = Field(min_length=1, max_length=80)
    city: str | None = None
    district: str | None = None
    town: str | None = None
    cuisine: str = Field(min_length=1, max_length=80)
    price_level: str
    mood_tags: list[str] = []
    kakao_place_id: str | None = None
    kakao_place_url: str | None = None
    address: str | None = None
    road_address: str | None = None
    phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class RestaurantNoteCreate(BaseModel):
    content: str = Field(min_length=10)
    tags: list[str] = []


class KakaoPlace(BaseModel):
    id: str
    place_name: str
    category_name: str
    address_name: str
    road_address_name: str
    phone: str
    place_url: str
    x: str
    y: str


class KakaoPlaceSearchResponse(BaseModel):
    query: str
    places: list[KakaoPlace]


class KakaoLocalValidationResponse(BaseModel):
    configured: bool
    query: str
    success: bool
    status_code: int | None = None
    place_count: int = 0
    message: str


class RestaurantResponse(BaseModel):
    id: str
    user_id: str | None
    name: str
    area: str
    city: str | None
    district: str | None
    town: str | None
    cuisine: str
    price_level: str
    mood_tags: list[str]
    signature_menus: list[str]
    kakao_place_id: str | None
    kakao_place_url: str | None
    address: str | None
    road_address: str | None
    phone: str | None
    latitude: float | None
    longitude: float | None
    note_count: int
    created_at: str


class RestaurantRecommendationRequest(BaseModel):
    user_id: str | None = None
    query: str = Field(min_length=1)
    area: str | None = None
    cuisine: TextFilter = None
    price_level: TextFilter = None
    tags: list[str] = []
    latitude: float | None = None
    longitude: float | None = None
    limit: int = Field(default=3, ge=1, le=5)


class RestaurantRecommendation(BaseModel):
    restaurant: RestaurantResponse
    reason: str
    evidence: list[str]
    menu_tip: str
    caution: str
    score: float


class RestaurantRecommendationsResponse(BaseModel):
    query: str
    recommendations: list[RestaurantRecommendation]


class RestaurantChatRequest(BaseModel):
    query: str = Field(min_length=1)
    message: str = Field(min_length=1)
    area: str | None = None
    tags: list[str] = []
    latitude: float | None = None
    longitude: float | None = None
    limit: int = Field(default=3, ge=1, le=5)
    session_id: str | None = None
    request_id: str | None = None


class RestaurantChatCancelRequest(BaseModel):
    session_id: str | None = None
    request_id: str | None = None


class RestaurantChatCancelResponse(BaseModel):
    cancelled: bool
    session_id: str | None = None
    request_id: str | None = None


class RestaurantChatResponse(BaseModel):
    session_id: str
    request_id: str
    cancelled: bool = False
    answer: str
    recommendations: list[RestaurantRecommendation]
    context: list[str]


class TasteAgentMessage(BaseModel):
    id: str
    session_id: str | None = None
    user_id: str | None
    role: str
    content: str
    retrieved_context: list[str]
    metadata: dict[str, Any] = {}
    created_at: str


class TasteAgentSession(BaseModel):
    id: str
    user_id: str | None
    title: str
    created_at: str
    updated_at: str
    messages: list[TasteAgentMessage]


class TasteAgentMessagesResponse(BaseModel):
    user_id: str | None
    messages: list[TasteAgentMessage]
    limit: int
    offset: int
    has_more: bool


class TasteAgentSessionsResponse(BaseModel):
    user_id: str | None
    sessions: list[TasteAgentSession]
    limit: int
    offset: int
    has_more: bool

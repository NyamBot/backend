from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    app: str
    vector_store: str
    database_url: str


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
    created_at: str
    last_login_at: str | None


class SourceCreate(BaseModel):
    user_id: str | None = None
    title: str = Field(min_length=1, max_length=120)
    transcript: str = Field(min_length=20)
    audience: str = "general creators"
    platform: str = "shorts"
    tone: str = "clear, energetic"
    goal: str = "awareness"


class SourceResponse(BaseModel):
    id: str
    title: str
    chunk_count: int


class SourceDetail(SourceResponse):
    user_id: str | None
    audience: str
    platform: str
    tone: str
    goal: str
    created_at: str


class ClipGenerateRequest(BaseModel):
    source_id: str
    title: str = "Untitled source"
    platform: str = "shorts"
    audience: str = "general creators"
    goal: str = "awareness"
    count: int = Field(default=3, ge=1, le=5)


class ClipIdea(BaseModel):
    id: str
    title: str
    hook: str
    summary: str
    platform: str
    duration_seconds: int
    hook_score: int
    audience_angle: str
    cta: str
    platform_fit: str
    source_moments: list[str]


class ClipIdeasResponse(BaseModel):
    source_id: str
    ideas: list[ClipIdea]


class ScriptRequest(BaseModel):
    source_id: str
    idea: ClipIdea


class ScriptPack(BaseModel):
    id: str | None = None
    source_id: str | None = None
    clip_idea_id: str | None = None
    title: str
    hook: str
    scene_plan: list[str]
    captions: list[str]
    b_roll: list[str]
    audio_direction: list[str]
    hashtags: list[str]
    license_checklist: list[str]
    created_at: str | None = None


class AgentChatRequest(BaseModel):
    source_id: str
    message: str = Field(min_length=1)


class AgentChatResponse(BaseModel):
    answer: str
    context: list[str]


class AgentMessage(BaseModel):
    id: str
    source_id: str
    role: str
    content: str
    retrieved_context: list[str]
    created_at: str


class AgentMessagesResponse(BaseModel):
    source_id: str
    messages: list[AgentMessage]


class RestaurantCreate(BaseModel):
    user_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    area: str = Field(min_length=1, max_length=80)
    cuisine: str = Field(min_length=1, max_length=80)
    price_level: str = "보통"
    mood_tags: list[str] = []
    signature_menus: list[str] = []
    note: str = Field(min_length=10)
    kakao_place_id: str | None = None
    kakao_place_url: str | None = None
    address: str | None = None
    road_address: str | None = None
    phone: str | None = None


class RestaurantResponse(BaseModel):
    id: str
    user_id: str | None
    name: str
    area: str
    cuisine: str
    price_level: str
    mood_tags: list[str]
    signature_menus: list[str]
    kakao_place_id: str | None
    kakao_place_url: str | None
    address: str | None
    road_address: str | None
    phone: str | None
    note_count: int
    created_at: str


class RestaurantRecommendationRequest(BaseModel):
    user_id: str | None = None
    query: str = Field(min_length=1)
    area: str | None = None
    cuisine: str | None = None
    price_level: str | None = None
    tags: list[str] = []
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


class RestaurantChatRequest(RestaurantRecommendationRequest):
    message: str = Field(min_length=1)


class RestaurantChatResponse(BaseModel):
    answer: str
    recommendations: list[RestaurantRecommendation]
    context: list[str]


class TasteAgentMessage(BaseModel):
    id: str
    user_id: str | None
    role: str
    content: str
    retrieved_context: list[str]
    created_at: str


class TasteAgentMessagesResponse(BaseModel):
    user_id: str | None
    messages: list[TasteAgentMessage]

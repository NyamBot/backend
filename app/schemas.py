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
    title: str
    hook: str
    scene_plan: list[str]
    captions: list[str]
    b_roll: list[str]
    audio_direction: list[str]
    hashtags: list[str]
    license_checklist: list[str]


class AgentChatRequest(BaseModel):
    source_id: str
    message: str = Field(min_length=1)


class AgentChatResponse(BaseModel):
    answer: str
    context: list[str]

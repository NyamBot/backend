from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    """Domain model for an authenticated NyamBot user."""

    id: str
    email: str
    display_name: str
    avatar_url: str | None
    auth_provider: str
    provider_subject: str | None
    role: str
    level_key: str
    level_points: int
    created_at: str
    last_login_at: str | None = None


@dataclass(frozen=True)
class UserLevel:
    """Domain model for the user's level and next-level progress."""

    user_id: str
    level_points: int
    level_key: str
    level_label: str
    current_level_min_points: int
    next_level_key: str | None
    next_level_label: str | None
    next_level_min_points: int | None
    points_to_next_level: int | None

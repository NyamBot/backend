from fastapi import APIRouter, HTTPException

from app.schemas import UserCreate, UserResponse
from app.services.restaurant_store import restaurant_store

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
def list_users() -> list[UserResponse]:
    return [UserResponse(**user) for user in restaurant_store.list_users()]


@router.post("", response_model=UserResponse)
def create_user(payload: UserCreate) -> UserResponse:
    user = restaurant_store.create_user(
        email=payload.email,
        display_name=payload.display_name,
        avatar_url=payload.avatar_url,
        auth_provider=payload.auth_provider,
        provider_subject=payload.provider_subject,
    )
    return UserResponse(**user)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: str) -> UserResponse:
    user = restaurant_store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**user)

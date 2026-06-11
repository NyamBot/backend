from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user
from app.schemas import UserCreate, UserLevelEventRequest, UserLevelEventResponse, UserLevelResponse, UserResponse
from app.services.restaurant_store import restaurant_store

router = APIRouter(prefix="/users", tags=["users"])


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


@router.get("/me/level", response_model=UserLevelResponse)
def get_my_level(current_user: UserResponse = Depends(get_current_user)) -> UserLevelResponse:
    level = restaurant_store.get_user_level(current_user.id)
    if level is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserLevelResponse(**level)


@router.post("/me/level/events", response_model=UserLevelEventResponse)
def add_my_level_event(
    payload: UserLevelEventRequest,
    current_user: UserResponse = Depends(get_current_user),
) -> UserLevelEventResponse:
    try:
        result = restaurant_store.add_user_level_event(current_user.id, payload.event_type)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="User not found")
    points_added, level = result
    return UserLevelEventResponse(
        event_type=payload.event_type,
        points_added=points_added,
        level=UserLevelResponse(**level),
    )


@router.delete("/me", status_code=204)
def delete_me(current_user: UserResponse = Depends(get_current_user)) -> None:
    deleted = restaurant_store.delete_user(current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")

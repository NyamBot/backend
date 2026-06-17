from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token
from app.schemas import UserResponse
from app.services.restaurant_store import restaurant_store


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserResponse:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(ErrorCode.LOGIN_REQUIRED, 401)

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise AppError(ErrorCode.INVALID_TOKEN, 401)

    user_id = payload.get("sub")
    if not isinstance(user_id, str):
        raise AppError(ErrorCode.INVALID_TOKEN_SUBJECT, 401)

    user = restaurant_store.get_user(user_id)
    if user is None:
        raise AppError(ErrorCode.USER_NOT_FOUND, 401)
    return UserResponse(**user)


def get_current_admin(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    if current_user.role != "admin":
        raise AppError(ErrorCode.ADMIN_REQUIRED, 403)
    return current_user


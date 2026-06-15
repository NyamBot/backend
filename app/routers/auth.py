from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.errors import AppError, ErrorCode
from app.core.security import create_access_token
from app.schemas import AuthCallbackResponse, AuthCodeExchangeRequest, AuthTokenResponse, UserResponse
from app.services.auth_exchange import auth_code_store
from app.services.kakao_auth import KakaoAuthError, build_login_url, fetch_kakao_profile
from app.services.restaurant_store import restaurant_store

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/kakao/login")
def kakao_login() -> RedirectResponse:
    try:
        login_url = build_login_url()
    except KakaoAuthError as error:
        raise AppError(ErrorCode.AUTH_PROVIDER_ERROR, 400, message=str(error)) from error
    return RedirectResponse(login_url)


@router.get("/kakao/callback", response_model=AuthCallbackResponse)
def kakao_callback(code: str | None = None, error: str | None = None) -> RedirectResponse:
    if error:
        return RedirectResponse(_frontend_redirect(auth_error=error))
    if not code:
        return RedirectResponse(_frontend_redirect(auth_error="missing_code"))

    try:
        profile = fetch_kakao_profile(code)
    except KakaoAuthError as auth_error:
        return RedirectResponse(_frontend_redirect(auth_error=str(auth_error)))

    user = restaurant_store.upsert_user(
        email=profile.email,
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        auth_provider="kakao",
        provider_subject=profile.provider_subject,
    )
    token = create_access_token(user["id"])
    auth_code = auth_code_store.issue(token)
    return RedirectResponse(_frontend_redirect(auth_code=auth_code))


@router.post("/session", response_model=AuthTokenResponse)
def exchange_auth_code(payload: AuthCodeExchangeRequest) -> AuthTokenResponse:
    token = auth_code_store.consume(payload.code)
    if not token:
        raise AppError(ErrorCode.INVALID_AUTH_CODE, 400)
    return AuthTokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def me(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    return current_user


def _frontend_redirect(**params: str) -> str:
    return f"{settings.frontend_url}?{urlencode(params)}"

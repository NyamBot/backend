from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import settings


KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_USER_ME_URL = "https://kapi.kakao.com/v2/user/me"


@dataclass
class KakaoProfile:
    provider_subject: str
    email: str
    display_name: str
    avatar_url: str | None


class KakaoAuthError(Exception):
    pass


def build_login_url() -> str:
    if not settings.kakao_client_id:
        raise KakaoAuthError("KAKAO_CLIENT_ID is not configured")

    params = httpx.QueryParams(
        {
            "response_type": "code",
            "client_id": settings.kakao_client_id,
            "redirect_uri": settings.kakao_redirect_uri,
        }
    )
    return f"https://kauth.kakao.com/oauth/authorize?{params}"


def fetch_kakao_profile(code: str) -> KakaoProfile:
    token = _exchange_code(code)
    return _fetch_profile(token)


def _exchange_code(code: str) -> str:
    if not settings.kakao_client_id:
        raise KakaoAuthError("KAKAO_CLIENT_ID is not configured")

    payload = {
        "grant_type": "authorization_code",
        "client_id": settings.kakao_client_id,
        "redirect_uri": settings.kakao_redirect_uri,
        "code": code,
    }
    if settings.kakao_client_secret:
        payload["client_secret"] = settings.kakao_client_secret

    response = httpx.post(KAKAO_TOKEN_URL, data=payload, timeout=10)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise KakaoAuthError(_extract_error_message(error.response)) from error

    access_token = response.json().get("access_token")
    if not isinstance(access_token, str):
        raise KakaoAuthError("Kakao access token was not returned")
    return access_token


def _fetch_profile(access_token: str) -> KakaoProfile:
    response = httpx.get(
        KAKAO_USER_ME_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise KakaoAuthError(_extract_error_message(error.response)) from error

    data = response.json()
    kakao_id = data.get("id")
    account = data.get("kakao_account") or {}
    profile = account.get("profile") or {}
    display_name = profile.get("nickname") or "NyamBot User"
    email = account.get("email") or f"kakao-{kakao_id}@nyambot.local"
    avatar_url = profile.get("profile_image_url")
    return KakaoProfile(
        provider_subject=str(kakao_id),
        email=str(email),
        display_name=str(display_name),
        avatar_url=str(avatar_url) if avatar_url else None,
    )


def _extract_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return "Kakao authentication failed"
    message = data.get("error_description") or data.get("msg") or data.get("message") or data.get("error")
    return str(message) if message else "Kakao authentication failed"


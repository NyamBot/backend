from __future__ import annotations

import httpx

from app.core.config import settings
from app.schemas import KakaoPlace


KAKAO_LOCAL_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


class KakaoLocalApiError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def search_places(
    query: str,
    size: int = 5,
    x: float | None = None,
    y: float | None = None,
    radius: int | None = None,
) -> list[KakaoPlace]:
    api_key = get_kakao_local_api_key()
    if not api_key:
        raise KakaoLocalApiError(400, "KAKAO_LOCAL_REST_API_KEY is not configured")

    params: dict[str, str | int | float] = {"query": query, "size": size}
    if x is not None and y is not None:
        params["x"] = x
        params["y"] = y
    if radius is not None:
        params["radius"] = radius

    try:
        response = httpx.get(
            KAKAO_LOCAL_SEARCH_URL,
            params=params,
            headers={"Authorization": f"KakaoAK {api_key}"},
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        detail = _extract_error_message(error.response)
        raise KakaoLocalApiError(error.response.status_code, detail) from error
    except httpx.HTTPError as error:
        raise KakaoLocalApiError(502, "카카오 장소 검색 API 호출에 실패했습니다.") from error

    return [
        KakaoPlace(
            id=document.get("id", ""),
            place_name=document.get("place_name", ""),
            category_name=document.get("category_name", ""),
            address_name=document.get("address_name", ""),
            road_address_name=document.get("road_address_name", ""),
            phone=document.get("phone", ""),
            place_url=document.get("place_url", ""),
            x=document.get("x", ""),
            y=document.get("y", ""),
        )
        for document in response.json().get("documents", [])
    ]


def get_kakao_local_api_key() -> str | None:
    return settings.kakao_local_rest_api_key or settings.kakao_client_id


def _extract_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return "카카오 장소 검색 API 응답을 처리하지 못했습니다."

    message = data.get("message")
    if isinstance(message, str) and message:
        return message
    error_type = data.get("errorType")
    if isinstance(error_type, str) and error_type:
        return error_type
    return "카카오 장소 검색 API 요청이 거절되었습니다."

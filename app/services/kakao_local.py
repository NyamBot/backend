from __future__ import annotations

import httpx

from app.core.config import settings
from app.schemas import KakaoPlace


KAKAO_LOCAL_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


def search_places(query: str, size: int = 5) -> list[KakaoPlace]:
    api_key = settings.kakao_local_rest_api_key or settings.kakao_client_id
    if not api_key:
        return []

    response = httpx.get(
        KAKAO_LOCAL_SEARCH_URL,
        params={"query": query, "size": size},
        headers={"Authorization": f"KakaoAK {api_key}"},
        timeout=10,
    )
    response.raise_for_status()
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

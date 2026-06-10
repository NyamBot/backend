import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user
from app.schemas import (
    RestaurantChatRequest,
    RestaurantChatResponse,
    RestaurantCreate,
    RestaurantNoteCreate,
    KakaoLocalValidationResponse,
    KakaoPlaceSearchResponse,
    RestaurantRecommendation,
    RestaurantRecommendationRequest,
    RestaurantRecommendationsResponse,
    RestaurantResponse,
    RestaurantUpdate,
    TasteAgentMessagesResponse,
    TasteAgentSessionsResponse,
    UserResponse,
)
from app.services.huggingface_chat import HuggingFaceChatError, huggingface_chat_service
from app.services.kakao_local import KakaoLocalApiError, get_kakao_local_api_key, search_places
from app.services.restaurant_store import restaurant_store

router = APIRouter(prefix="/restaurants", tags=["restaurants"])

NEARBY_RADIUS_METERS = 2000
NEARBY_RADIUS_KM = NEARBY_RADIUS_METERS / 1000
MIN_CHAT_RECOMMENDATIONS = 3
MAX_AI_CANDIDATES = 12
KAKAO_SEARCH_SIZE = 15


@dataclass(frozen=True)
class LocationCriteria:
    city: str | None = None
    district: str | None = None
    neighborhood: str | None = None

    @property
    def display(self) -> str:
        return " ".join(part for part in (self.city, self.district, self.neighborhood) if part)

    @property
    def store_area(self) -> str | None:
        return self.neighborhood or self.district or self.city


AREA_ALIASES = {
    "강남": LocationCriteria(city="서울", district="강남구"),
    "강남구": LocationCriteria(city="서울", district="강남구"),
    "서초": LocationCriteria(city="서울", district="서초구"),
    "서초구": LocationCriteria(city="서울", district="서초구"),
    "서초동": LocationCriteria(city="서울", district="서초구", neighborhood="서초동"),
    "방배": LocationCriteria(city="서울", district="서초구", neighborhood="방배동"),
    "방배동": LocationCriteria(city="서울", district="서초구", neighborhood="방배동"),
    "잠실": LocationCriteria(city="서울", district="송파구", neighborhood="잠실동"),
    "잠실동": LocationCriteria(city="서울", district="송파구", neighborhood="잠실동"),
    "송파": LocationCriteria(city="서울", district="송파구"),
    "송파구": LocationCriteria(city="서울", district="송파구"),
    "성수": LocationCriteria(city="서울", district="성동구", neighborhood="성수동"),
    "성수동": LocationCriteria(city="서울", district="성동구", neighborhood="성수동"),
    "홍대": LocationCriteria(city="서울", district="마포구", neighborhood="상수동"),
    "합정": LocationCriteria(city="서울", district="마포구", neighborhood="합정동"),
    "합정동": LocationCriteria(city="서울", district="마포구", neighborhood="합정동"),
    "연남": LocationCriteria(city="서울", district="마포구", neighborhood="연남동"),
    "연남동": LocationCriteria(city="서울", district="마포구", neighborhood="연남동"),
    "이태원": LocationCriteria(city="서울", district="용산구", neighborhood="이태원동"),
    "한남": LocationCriteria(city="서울", district="용산구", neighborhood="한남동"),
    "한남동": LocationCriteria(city="서울", district="용산구", neighborhood="한남동"),
    "종로": LocationCriteria(city="서울", district="종로구"),
    "종로구": LocationCriteria(city="서울", district="종로구"),
    "명동": LocationCriteria(city="서울", district="중구", neighborhood="명동"),
    "을지로": LocationCriteria(city="서울", district="중구", neighborhood="을지로"),
    "여의도": LocationCriteria(city="서울", district="영등포구", neighborhood="여의도동"),
    "마포": LocationCriteria(city="서울", district="마포구"),
    "마포구": LocationCriteria(city="서울", district="마포구"),
    "신림": LocationCriteria(city="서울", district="관악구", neighborhood="신림동"),
    "신림동": LocationCriteria(city="서울", district="관악구", neighborhood="신림동"),
    "부산": LocationCriteria(city="부산"),
    "부산시": LocationCriteria(city="부산"),
    "해운대": LocationCriteria(city="부산", district="해운대구"),
    "해운대구": LocationCriteria(city="부산", district="해운대구"),
    "대구": LocationCriteria(city="대구"),
    "인천": LocationCriteria(city="인천"),
    "광주": LocationCriteria(city="광주"),
    "대전": LocationCriteria(city="대전"),
    "울산": LocationCriteria(city="울산"),
    "세종": LocationCriteria(city="세종"),
}

SEOUL_DISTRICTS = (
    "강남구",
    "강동구",
    "강북구",
    "강서구",
    "관악구",
    "광진구",
    "구로구",
    "금천구",
    "노원구",
    "도봉구",
    "동대문구",
    "동작구",
    "마포구",
    "서대문구",
    "서초구",
    "성동구",
    "성북구",
    "송파구",
    "양천구",
    "영등포구",
    "용산구",
    "은평구",
    "종로구",
    "중구",
    "중랑구",
)

for district in SEOUL_DISTRICTS:
    AREA_ALIASES.setdefault(district, LocationCriteria(city="서울", district=district))
    AREA_ALIASES.setdefault(district.removesuffix("구"), LocationCriteria(city="서울", district=district))

CITY_ALIASES = {
    "서울": "서울",
    "서울시": "서울",
    "부산": "부산",
    "부산시": "부산",
    "대구": "대구",
    "대구시": "대구",
    "인천": "인천",
    "인천시": "인천",
    "광주": "광주",
    "광주시": "광주",
    "대전": "대전",
    "대전시": "대전",
    "울산": "울산",
    "울산시": "울산",
    "세종": "세종",
    "세종시": "세종",
}


@router.post("", response_model=RestaurantResponse)
def create_restaurant(
    payload: RestaurantCreate,
    current_user: UserResponse = Depends(get_current_user),
) -> RestaurantResponse:
    return restaurant_store.create_restaurant(payload.model_copy(update={"user_id": current_user.id}))


@router.get("", response_model=list[RestaurantResponse])
def list_restaurants(
    city: str | None = None,
    district: str | None = None,
    town: str | None = None,
    query: str | None = None,
    rating_level: str | None = None,
    current_user: UserResponse = Depends(get_current_user),
) -> list[RestaurantResponse]:
    return restaurant_store.list_restaurants(
        user_id=current_user.id,
        city=city,
        district=district,
        town=town,
        query=query,
        rating_level=rating_level,
    )


@router.get("/kakao/search", response_model=KakaoPlaceSearchResponse)
def search_kakao_places(query: str, size: int = 5) -> KakaoPlaceSearchResponse:
    try:
        places = search_places(query=query, size=min(max(size, 1), 15))
    except KakaoLocalApiError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error
    return KakaoPlaceSearchResponse(query=query, places=places)


@router.get("/kakao/validate", response_model=KakaoLocalValidationResponse)
def validate_kakao_local_api_key(query: str = "성수 맛집") -> KakaoLocalValidationResponse:
    if not get_kakao_local_api_key():
        return KakaoLocalValidationResponse(
            configured=False,
            query=query,
            success=False,
            message="KAKAO_LOCAL_REST_API_KEY is not configured",
        )

    try:
        places = search_places(query=query, size=1)
    except KakaoLocalApiError as error:
        return KakaoLocalValidationResponse(
            configured=True,
            query=query,
            success=False,
            status_code=error.status_code,
            message=error.message,
        )
    return KakaoLocalValidationResponse(
        configured=True,
        query=query,
        success=True,
        status_code=200,
        place_count=len(places),
        message="Kakao Local REST API key is valid",
    )


@router.post("/{restaurant_id}/notes", response_model=RestaurantResponse)
def add_restaurant_note(
    restaurant_id: str,
    payload: RestaurantNoteCreate,
    current_user: UserResponse = Depends(get_current_user),
) -> RestaurantResponse:
    target = restaurant_store.get_restaurant(restaurant_id)
    if target is None or target.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    restaurant = restaurant_store.add_note(restaurant_id, payload)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return restaurant


@router.put("/{restaurant_id}", response_model=RestaurantResponse)
def update_restaurant(
    restaurant_id: str,
    payload: RestaurantUpdate,
    current_user: UserResponse = Depends(get_current_user),
) -> RestaurantResponse:
    target = restaurant_store.get_restaurant(restaurant_id)
    if target is None or target.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    restaurant = restaurant_store.update_restaurant(restaurant_id, payload)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return restaurant


@router.delete("/{restaurant_id}", status_code=204)
def delete_restaurant(
    restaurant_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> None:
    target = restaurant_store.get_restaurant(restaurant_id)
    if target is None or target.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    restaurant_store.delete_restaurant(restaurant_id)


@router.post("/recommendations", response_model=RestaurantRecommendationsResponse)
def recommend_restaurants(
    payload: RestaurantRecommendationRequest,
    current_user: UserResponse = Depends(get_current_user),
) -> RestaurantRecommendationsResponse:
    recommendations = restaurant_store.recommend(
        query=payload.query,
        user_id=current_user.id,
        area=payload.area,
        cuisine=payload.cuisine,
        price_level=payload.price_level,
        tags=payload.tags,
        latitude=payload.latitude,
        longitude=payload.longitude,
        limit=payload.limit,
    )
    return RestaurantRecommendationsResponse(query=payload.query, recommendations=recommendations)


@router.post("/chat", response_model=RestaurantChatResponse)
def chat(
    payload: RestaurantChatRequest,
    current_user: UserResponse = Depends(get_current_user),
) -> RestaurantChatResponse:
    query = payload.message or payload.query
    location_criteria = _extract_location_criteria(query, payload.area)
    requested_area = location_criteria.display if location_criteria else None
    area_filter = location_criteria.store_area if location_criteria else None
    effective_limit = max(payload.limit, MIN_CHAT_RECOMMENDATIONS)
    session_id = restaurant_store.ensure_chat_session(current_user.id, payload.session_id, query)
    recommendations = restaurant_store.recommend(
        query=query,
        user_id=current_user.id,
        area=area_filter,
        cuisine=payload.cuisine,
        price_level=payload.price_level,
        tags=payload.tags,
        latitude=payload.latitude,
        longitude=payload.longitude,
        limit=MAX_AI_CANDIDATES,
    )
    has_saved_restaurants = bool(restaurant_store.list_restaurants(user_id=current_user.id))
    used_nearby_fallback = False
    if location_criteria and len(recommendations) < MAX_AI_CANDIDATES:
        area_recommendations = _build_kakao_area_recommendations(
            query=query,
            cuisine=payload.cuisine,
            location_criteria=location_criteria,
            limit=MAX_AI_CANDIDATES,
        )
        if area_recommendations:
            recommendations = _merge_recommendations(recommendations, area_recommendations, MAX_AI_CANDIDATES)
            used_nearby_fallback = True
    elif payload.latitude is not None and payload.longitude is not None and not _has_nearby_saved_recommendation(
        recommendations,
        payload.latitude,
        payload.longitude,
        NEARBY_RADIUS_KM,
    ):
        nearby_recommendations = _build_kakao_nearby_recommendations(
            query=query,
            cuisine=payload.cuisine,
            latitude=payload.latitude,
            longitude=payload.longitude,
            limit=MAX_AI_CANDIDATES,
        )
        if nearby_recommendations:
            recommendations = _merge_recommendations(recommendations, nearby_recommendations, MAX_AI_CANDIDATES)
            used_nearby_fallback = True
    if not recommendations and not has_saved_restaurants:
        recommendations = _build_fallback_recommendations(query, effective_limit)
    recommendations = recommendations[:MAX_AI_CANDIDATES]
    rerank_error: str | None = None
    try:
        reranked_recommendations = huggingface_chat_service.rerank_restaurant_candidates(
            query=query,
            recommendations=recommendations,
            requested_area=requested_area,
            area_filter=area_filter,
            latitude=payload.latitude,
            longitude=payload.longitude,
            limit=effective_limit,
        )
    except HuggingFaceChatError as error:
        reranked_recommendations = []
        rerank_error = str(error)
    if reranked_recommendations:
        recommendations = _apply_ai_rerank(recommendations, reranked_recommendations, effective_limit)
    else:
        recommendations = recommendations[:effective_limit]
    context = [
        evidence
        for recommendation in recommendations
        for evidence in recommendation.evidence
    ]
    answer_provider = "template"
    ai_error: str | None = None
    try:
        ai_answer = huggingface_chat_service.generate_restaurant_answer(
            query,
            recommendations,
            fallback=not has_saved_restaurants or used_nearby_fallback,
            requested_area=requested_area,
            area_filter=area_filter,
        )
    except HuggingFaceChatError as error:
        ai_answer = None
        ai_error = str(error)
    if ai_answer:
        answer = ai_answer
        answer_provider = f"huggingface:{huggingface_chat_service.model}"
    else:
        answer = _build_answer(query, recommendations, fallback=not has_saved_restaurants or used_nearby_fallback)
    request_metadata = {
        "area": requested_area,
        "area_filter": area_filter,
        "location_criteria": {
            "city": location_criteria.city,
            "district": location_criteria.district,
            "neighborhood": location_criteria.neighborhood,
        }
        if location_criteria
        else None,
        "requested_area_source": "payload" if payload.area else ("query" if requested_area else None),
        "cuisine": payload.cuisine,
        "price_level": payload.price_level,
        "tags": payload.tags,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "limit": payload.limit,
    }
    restaurant_store.save_message(session_id, current_user.id, "user", query, [], request_metadata)
    restaurant_store.save_message(
        session_id,
        current_user.id,
        "assistant",
        answer,
        context,
        {
            "recommendation_count": len(recommendations),
            "restaurant_names": [recommendation.restaurant.name for recommendation in recommendations],
            "recommendations": [recommendation.model_dump(mode="json") for recommendation in recommendations],
            "answer_provider": answer_provider,
            "ai_error": ai_error,
            "rerank_error": rerank_error,
            "used_nearby_fallback": used_nearby_fallback,
        },
    )
    restaurant_store.touch_chat_session(session_id)
    return RestaurantChatResponse(session_id=session_id, answer=answer, recommendations=recommendations, context=context)


@router.get("/chat/messages", response_model=TasteAgentMessagesResponse)
def list_messages(current_user: UserResponse = Depends(get_current_user)) -> TasteAgentMessagesResponse:
    return TasteAgentMessagesResponse(
        user_id=current_user.id,
        messages=restaurant_store.list_messages(current_user.id),
    )


@router.get("/chat/sessions", response_model=TasteAgentSessionsResponse)
def list_sessions(current_user: UserResponse = Depends(get_current_user)) -> TasteAgentSessionsResponse:
    return TasteAgentSessionsResponse(
        user_id=current_user.id,
        sessions=restaurant_store.list_sessions(current_user.id),
    )


@router.get("/{restaurant_id}", response_model=RestaurantResponse)
def get_restaurant(
    restaurant_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> RestaurantResponse:
    restaurant = restaurant_store.get_restaurant(restaurant_id)
    if restaurant is None or restaurant.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return restaurant


def _build_answer(query: str, recommendations, fallback: bool = False) -> str:
    if not recommendations:
        return (
            "저장된 맛집 메모에서 조건에 맞는 후보를 찾지 못했어요. "
            "지역, 음식 종류, 분위기 메모를 먼저 등록하면 더 정확하게 추천할 수 있습니다."
        )

    lines = [
        (
            f"아직 저장된 맛집이 없어서 '{query}' 기준으로 바로 가기 좋은 후보를 3순위로 골랐어요."
            if fallback
            else f"'{query}' 기준으로 저장된 메모와 벡터 검색 결과를 함께 보고 3순위로 추천했어요."
        ),
        "",
    ]
    for index, recommendation in enumerate(recommendations, start=1):
        restaurant = recommendation.restaurant
        evidence = recommendation.evidence[0] if recommendation.evidence else "저장된 메모가 이 조건과 유사합니다."
        lines.extend(
            [
                f"{index}. {restaurant.name}",
                f"- 지역/종류: {restaurant.area} · {restaurant.cuisine} · {restaurant.price_level}",
                f"- 추천 이유: {recommendation.reason}",
                f"- 근거 메모: {evidence}",
                f"- {recommendation.menu_tip}",
                f"- 주의: {recommendation.caution}",
            ]
        )
        if restaurant.kakao_place_url:
            lines.append(f"- 카카오 링크: {restaurant.kakao_place_url}")
        lines.append("")
    return "\n".join(lines).strip()


def _build_kakao_area_recommendations(
    query: str,
    cuisine: str | None,
    location_criteria: LocationCriteria,
    limit: int,
) -> list[RestaurantRecommendation]:
    search_area = location_criteria.display
    places = _search_kakao_places_broadly(search_area, cuisine, query)
    places = _filter_places_by_location(places, location_criteria)
    return _recommendations_from_kakao_places(
        places=places,
        limit=limit,
        reason_prefix=f"{search_area}에 저장된 맛집 후보가 부족해 카카오 장소 검색에서 찾은",
    )


def _build_kakao_nearby_recommendations(
    query: str,
    cuisine: str | None,
    latitude: float,
    longitude: float,
    limit: int,
) -> list[RestaurantRecommendation]:
    search_queries = _build_kakao_search_queries("", cuisine, query)
    places = []
    for search_query in search_queries:
        try:
            places.extend(
                search_places(
                    query=search_query,
                    size=min(max(limit, 1), 5),
                    x=longitude,
                    y=latitude,
                    radius=NEARBY_RADIUS_METERS,
                )
            )
        except KakaoLocalApiError:
            continue
    places = _dedupe_kakao_places(places)

    return _recommendations_from_kakao_places(
        places=places,
        limit=limit,
        reason_prefix="근방에 저장된 맛집이 없어 카카오 장소 검색에서 찾은",
        latitude=latitude,
        longitude=longitude,
    )


def _recommendations_from_kakao_places(
    places,
    limit: int,
    reason_prefix: str,
    latitude: float | None = None,
    longitude: float | None = None,
) -> list[RestaurantRecommendation]:
    created_at = datetime.now(timezone.utc).isoformat()
    recommendations: list[RestaurantRecommendation] = []
    for index, place in enumerate(places[:limit], start=1):
        category_parts = [part.strip() for part in place.category_name.split(">") if part.strip()]
        cuisine_name = category_parts[-1] if category_parts else "맛집"
        address_text = place.road_address_name or place.address_name
        area = _extract_area(address_text)
        city, district, town = _extract_location_parts(address_text)
        latitude_value = _parse_float(place.y)
        longitude_value = _parse_float(place.x)
        distance = _distance_km(latitude, longitude, latitude_value, longitude_value)
        distance_hint = f" 현재 위치에서 약 {distance:.1f}km 거리입니다." if distance is not None else ""
        restaurant = RestaurantResponse(
            id=f"kakao-{place.id}",
            user_id=None,
            name=place.place_name,
            area=area,
            city=city,
            district=district,
            town=town,
            cuisine=cuisine_name,
            price_level="",
            mood_tags=["근방 추천"],
            signature_menus=[],
            kakao_place_id=place.id,
            kakao_place_url=place.place_url,
            address=place.address_name or None,
            road_address=place.road_address_name or None,
            phone=place.phone or None,
            latitude=latitude_value,
            longitude=longitude_value,
            image_url=None,
            rating_level="맛남",
            note_count=0,
            created_at=created_at,
        )
        recommendations.append(
            RestaurantRecommendation(
                restaurant=restaurant,
                reason=f"{reason_prefix} {index}순위 후보입니다.{distance_hint}",
                evidence=[
                    _build_kakao_recommendation_reason(place.place_name, cuisine_name, area, distance)
                ],
                menu_tip="카카오맵에서 메뉴와 매장 정보를 확인해보세요.",
                caution="",
                score=round(max(0.5, 0.9 - (index - 1) * 0.06), 4),
            )
        )
    return recommendations


def _build_kakao_recommendation_reason(
    place_name: str,
    cuisine: str,
    area: str,
    distance: float | None,
) -> str:
    distance_text = f" 현재 위치에서 약 {distance:.1f}km 거리라 이동 부담도 적어요." if distance is not None else ""
    return f"{area}에서 찾은 {cuisine} 후보입니다.{distance_text}"


def _build_kakao_search_queries(
    search_area: str,
    cuisine: str | None,
    fallback_query: str,
) -> list[str]:
    area_prefix = f"{search_area} " if search_area else ""
    if cuisine:
        base_terms = [f"{cuisine} 맛집"]
    else:
        base_terms = ["맛집", "식당"]

    queries = [f"{area_prefix}{term}".strip() for term in base_terms]
    fallback = _normalize_nearby_query(fallback_query) if fallback_query else ""
    if fallback and fallback not in queries:
        queries.append(fallback)
    return queries


def _search_kakao_places_broadly(search_area: str, cuisine: str | None, query: str):
    places = []
    for search_query in _build_kakao_search_queries(search_area, cuisine, query):
        try:
            places.extend(search_places(query=search_query, size=KAKAO_SEARCH_SIZE))
        except KakaoLocalApiError:
            continue
    return _dedupe_kakao_places(places)


def _dedupe_kakao_places(places):
    deduped = []
    seen: set[str] = set()
    for place in places:
        key = place.id or f"{place.place_name}:{place.address_name}:{place.road_address_name}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(place)
    return deduped


def _merge_recommendations(
    primary: list[RestaurantRecommendation],
    fallback: list[RestaurantRecommendation],
    limit: int,
) -> list[RestaurantRecommendation]:
    merged: list[RestaurantRecommendation] = []
    seen: set[str] = set()
    for recommendation in primary + fallback:
        restaurant = recommendation.restaurant
        key = restaurant.kakao_place_id or restaurant.name
        if key in seen:
            continue
        seen.add(key)
        merged.append(recommendation)
        if len(merged) >= limit:
            break
    return merged


def _apply_ai_rerank(
    recommendations: list[RestaurantRecommendation],
    ranked_items: list[dict],
    limit: int,
) -> list[RestaurantRecommendation]:
    by_id = {recommendation.restaurant.id: recommendation for recommendation in recommendations}
    selected: list[RestaurantRecommendation] = []
    selected_ids: set[str] = set()
    for item in ranked_items:
        candidate_id = str(item.get("candidate_id", ""))
        recommendation = by_id.get(candidate_id)
        if recommendation is None or candidate_id in selected_ids:
            continue
        reason = str(item.get("reason") or recommendation.reason).strip()
        if reason:
            recommendation = recommendation.model_copy(update={"evidence": [reason]})
        selected.append(recommendation)
        selected_ids.add(candidate_id)
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        for recommendation in recommendations:
            if recommendation.restaurant.id in selected_ids:
                continue
            selected.append(recommendation)
            if len(selected) >= limit:
                break
    return selected


def _extract_location_criteria(query: str, payload_area: str | None = None) -> LocationCriteria | None:
    source = payload_area or _select_location_text(query)
    compact_source = source.replace(" ", "")
    for keyword in sorted(AREA_ALIASES, key=len, reverse=True):
        if keyword in compact_source:
            alias_criteria = AREA_ALIASES[keyword]
            parsed_neighborhood = _find_first_area_token(source, ("읍", "면", "동", "가", "리"))
            if parsed_neighborhood and not alias_criteria.neighborhood:
                return LocationCriteria(
                    city=alias_criteria.city,
                    district=alias_criteria.district,
                    neighborhood=parsed_neighborhood,
                )
            return alias_criteria

    city = _find_city_alias(source) or _find_first_area_token(source, ("특별시", "광역시", "자치시", "도", "시"))
    district = _find_first_area_token(source, ("구", "군"))
    neighborhood = _find_first_area_token(source, ("읍", "면", "동", "가", "리"))
    if city or district or neighborhood:
        return LocationCriteria(city=city, district=district, neighborhood=neighborhood)
    return None


def _select_location_text(query: str) -> str:
    for marker in ("말고", "아니고", "보다는"):
        if marker in query:
            return query.rsplit(marker, 1)[-1]
    return query


def _find_city_alias(text: str) -> str | None:
    compact_text = text.replace(" ", "")
    for keyword in sorted(CITY_ALIASES, key=len, reverse=True):
        if keyword in compact_text:
            return CITY_ALIASES[keyword]
    return None


def _find_first_area_token(text: str, suffixes: tuple[str, ...]) -> str | None:
    suffix_pattern = "|".join(re.escape(suffix) for suffix in suffixes)
    matches = re.findall(rf"[가-힣]{{1,}}(?:{suffix_pattern})", text)
    return matches[0] if matches else None


def _filter_places_by_location(places, location_criteria: LocationCriteria):
    required_keywords = [
        location_criteria.city,
        location_criteria.district,
        location_criteria.neighborhood,
    ]
    required_keywords = [keyword for keyword in required_keywords if keyword]
    filtered = []
    for place in places:
        address = f"{place.address_name} {place.road_address_name}"
        if all(keyword in address for keyword in required_keywords):
            filtered.append(place)
    return filtered


def _normalize_nearby_query(query: str) -> str:
    normalized = query.strip()
    return normalized if "맛집" in normalized else f"{normalized} 맛집"


def _extract_area(address: str) -> str:
    parts = address.split()
    if len(parts) >= 3:
        return " ".join(parts[:3])
    if len(parts) >= 2:
        return " ".join(parts[:2])
    return address or "근방"


def _extract_location_parts(address: str) -> tuple[str | None, str | None, str | None]:
    parts = address.split()
    city = parts[0] if len(parts) >= 1 else None
    district = parts[1] if len(parts) >= 2 else None
    town = next((part for part in parts[2:] if re.search(r"(동|읍|면|리|가)$", part)), None)
    return city, district, town


def _parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_nearby_saved_recommendation(
    recommendations: list[RestaurantRecommendation],
    latitude: float,
    longitude: float,
    radius_km: float,
) -> bool:
    for recommendation in recommendations:
        restaurant = recommendation.restaurant
        distance = _distance_km(latitude, longitude, restaurant.latitude, restaurant.longitude)
        if distance is not None and distance <= radius_km:
            return True
    return False


def _distance_km(
    left_latitude: float | None,
    left_longitude: float | None,
    right_latitude: float | None,
    right_longitude: float | None,
) -> float | None:
    if None in (left_latitude, left_longitude, right_latitude, right_longitude):
        return None
    earth_radius_km = 6371.0
    lat1 = math.radians(float(left_latitude))
    lat2 = math.radians(float(right_latitude))
    delta_lat = math.radians(float(right_latitude) - float(left_latitude))
    delta_lon = math.radians(float(right_longitude) - float(left_longitude))
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return earth_radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _build_fallback_recommendations(query: str, limit: int) -> list[RestaurantRecommendation]:
    created_at = datetime.now(timezone.utc).isoformat()
    query_hint = query.strip() or "오늘 식사"
    options = [
        {
            "id": "fallback-seongsu-date",
            "name": "성수 조용한 비스트로",
            "area": "성수",
            "cuisine": "양식",
            "price_level": "2~3만원",
            "mood_tags": ["조용함", "데이트", "예약 추천"],
            "signature_menus": ["파스타", "스테이크"],
            "reason": f"'{query_hint}'에 맞춰 대화하기 좋고 실패 확률이 낮은 분위기의 1순위 후보입니다.",
            "evidence": "저장된 맛집이 없어 일반적인 방문 목적, 분위기, 접근성을 기준으로 골랐어요.",
            "caution": "실제 매장명은 카카오 장소 검색에서 영업 중인 곳으로 확인해 주세요.",
        },
        {
            "id": "fallback-hapjeong-korean",
            "name": "합정 담백한 한식집",
            "area": "합정",
            "cuisine": "한식",
            "price_level": "1~2만원",
            "mood_tags": ["혼밥", "친구", "깔끔함"],
            "signature_menus": ["정식", "국밥"],
            "reason": "메뉴 호불호가 적고 혼밥부터 가벼운 약속까지 커버하기 좋아 2순위로 추천합니다.",
            "evidence": "저장된 메모 대신 폭넓게 먹기 좋은 메뉴와 편한 분위기를 우선했습니다.",
            "caution": "점심 피크 시간 웨이팅 여부를 지도 앱에서 확인하면 좋아요.",
        },
        {
            "id": "fallback-yeonnam-asian",
            "name": "연남 캐주얼 아시안 다이닝",
            "area": "연남",
            "cuisine": "아시안",
            "price_level": "2~3만원",
            "mood_tags": ["캐주얼", "데이트", "친구"],
            "signature_menus": ["쌀국수", "볶음밥"],
            "reason": "분위기는 가볍고 메뉴 선택지는 넓어서 즉흥 약속용 3순위 후보로 좋습니다.",
            "evidence": "저장 데이터가 쌓이기 전까지는 지역성, 메뉴 다양성, 무난함을 기준으로 추천합니다.",
            "caution": "취향 메모를 저장하면 다음 추천부터 실제 저장한 장소 중심으로 바뀝니다.",
        },
    ]
    recommendations = []
    for score, option in zip([0.93, 0.87, 0.81], options[:limit], strict=False):
        restaurant = RestaurantResponse(
            id=option["id"],
            user_id=None,
            name=option["name"],
            area=option["area"],
            city=None,
            district=None,
            town=None,
            cuisine=option["cuisine"],
            price_level=option["price_level"],
            mood_tags=option["mood_tags"],
            signature_menus=option["signature_menus"],
            kakao_place_id=None,
            kakao_place_url=None,
            address=None,
            road_address=None,
            phone=None,
            latitude=None,
            longitude=None,
            image_url=None,
            rating_level="맛남",
            note_count=0,
            created_at=created_at,
        )
        recommendations.append(
            RestaurantRecommendation(
                restaurant=restaurant,
                reason=option["reason"],
                evidence=[option["evidence"]],
                menu_tip=f"추천 포인트: {', '.join(option['signature_menus'])}",
                caution=option["caution"],
                score=score,
            )
        )
    return recommendations

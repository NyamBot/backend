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
    TasteAgentMessagesResponse,
    UserResponse,
)
from app.services.kakao_local import KakaoLocalApiError, get_kakao_local_api_key, search_places
from app.services.restaurant_store import restaurant_store

router = APIRouter(prefix="/api/restaurants", tags=["restaurants"])


@router.post("", response_model=RestaurantResponse)
def create_restaurant(
    payload: RestaurantCreate,
    current_user: UserResponse = Depends(get_current_user),
) -> RestaurantResponse:
    return restaurant_store.create_restaurant(payload.model_copy(update={"user_id": current_user.id}))


@router.get("", response_model=list[RestaurantResponse])
def list_restaurants(current_user: UserResponse = Depends(get_current_user)) -> list[RestaurantResponse]:
    return restaurant_store.list_restaurants(user_id=current_user.id)


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
        limit=payload.limit,
    )
    return RestaurantRecommendationsResponse(query=payload.query, recommendations=recommendations)


@router.post("/chat", response_model=RestaurantChatResponse)
def chat(
    payload: RestaurantChatRequest,
    current_user: UserResponse = Depends(get_current_user),
) -> RestaurantChatResponse:
    query = payload.message or payload.query
    recommendations = restaurant_store.recommend(
        query=query,
        user_id=current_user.id,
        area=payload.area,
        cuisine=payload.cuisine,
        price_level=payload.price_level,
        tags=payload.tags,
        limit=payload.limit,
    )
    has_saved_restaurants = bool(restaurant_store.list_restaurants(user_id=current_user.id))
    if not recommendations and not has_saved_restaurants:
        recommendations = _build_fallback_recommendations(query, payload.limit)
    context = [
        evidence
        for recommendation in recommendations
        for evidence in recommendation.evidence
    ]
    answer = _build_answer(query, recommendations, fallback=not has_saved_restaurants)
    restaurant_store.save_message(current_user.id, "user", query, [])
    restaurant_store.save_message(current_user.id, "assistant", answer, context)
    return RestaurantChatResponse(answer=answer, recommendations=recommendations, context=context)


@router.get("/chat/messages", response_model=TasteAgentMessagesResponse)
def list_messages(current_user: UserResponse = Depends(get_current_user)) -> TasteAgentMessagesResponse:
    return TasteAgentMessagesResponse(
        user_id=current_user.id,
        messages=restaurant_store.list_messages(current_user.id),
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


def _build_fallback_recommendations(query: str, limit: int) -> list[RestaurantRecommendation]:
    created_at = datetime.now(timezone.utc).isoformat()
    query_hint = query.strip() or "오늘 식사"
    options = [
        {
            "id": "fallback-seongsu-date",
            "name": "성수 조용한 비스트로",
            "area": "성수",
            "cuisine": "양식",
            "price_level": "보통",
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
            "price_level": "무난",
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
            "price_level": "보통",
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
            note_count=0,
            created_at=created_at,
        )
        recommendations.append(
            RestaurantRecommendation(
                restaurant=restaurant,
                reason=option["reason"],
                evidence=[option["evidence"]],
                menu_tip=f"추천 메뉴: {', '.join(option['signature_menus'])}",
                caution=option["caution"],
                score=score,
            )
        )
    return recommendations

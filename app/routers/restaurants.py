from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user
from app.schemas import (
    RestaurantChatRequest,
    RestaurantChatResponse,
    RestaurantCreate,
    RestaurantNoteCreate,
    KakaoPlaceSearchResponse,
    RestaurantRecommendationRequest,
    RestaurantRecommendationsResponse,
    RestaurantResponse,
    TasteAgentMessagesResponse,
    UserResponse,
)
from app.services.kakao_local import KakaoLocalApiError, search_places
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
    context = [
        evidence
        for recommendation in recommendations
        for evidence in recommendation.evidence
    ]
    answer = _build_answer(query, recommendations)
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


def _build_answer(query: str, recommendations) -> str:
    if not recommendations:
        return (
            "저장된 맛집 메모에서 조건에 맞는 후보를 찾지 못했어요. "
            "지역, 음식 종류, 분위기 메모를 먼저 등록하면 더 정확하게 추천할 수 있습니다."
        )

    lines = [
        f"'{query}' 기준으로 저장된 메모와 벡터 검색 결과를 함께 보고 추천했어요.",
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

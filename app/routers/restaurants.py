from fastapi import APIRouter, HTTPException

from app.schemas import (
    RestaurantChatRequest,
    RestaurantChatResponse,
    RestaurantCreate,
    RestaurantRecommendationRequest,
    RestaurantRecommendationsResponse,
    RestaurantResponse,
    TasteAgentMessagesResponse,
)
from app.services.restaurant_store import restaurant_store

router = APIRouter(prefix="/api/restaurants", tags=["restaurants"])


@router.post("", response_model=RestaurantResponse)
def create_restaurant(payload: RestaurantCreate) -> RestaurantResponse:
    return restaurant_store.create_restaurant(payload)


@router.get("", response_model=list[RestaurantResponse])
def list_restaurants(user_id: str | None = None) -> list[RestaurantResponse]:
    return restaurant_store.list_restaurants(user_id=user_id)


@router.get("/{restaurant_id}", response_model=RestaurantResponse)
def get_restaurant(restaurant_id: str) -> RestaurantResponse:
    restaurant = restaurant_store.get_restaurant(restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return restaurant


@router.post("/recommendations", response_model=RestaurantRecommendationsResponse)
def recommend_restaurants(payload: RestaurantRecommendationRequest) -> RestaurantRecommendationsResponse:
    recommendations = restaurant_store.recommend(
        query=payload.query,
        user_id=payload.user_id,
        area=payload.area,
        cuisine=payload.cuisine,
        price_level=payload.price_level,
        tags=payload.tags,
        limit=payload.limit,
    )
    return RestaurantRecommendationsResponse(query=payload.query, recommendations=recommendations)


@router.post("/chat", response_model=RestaurantChatResponse)
def chat(payload: RestaurantChatRequest) -> RestaurantChatResponse:
    query = payload.message or payload.query
    recommendations = restaurant_store.recommend(
        query=query,
        user_id=payload.user_id,
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
    restaurant_store.save_message(payload.user_id, "user", query, [])
    restaurant_store.save_message(payload.user_id, "assistant", answer, context)
    return RestaurantChatResponse(answer=answer, recommendations=recommendations, context=context)


@router.get("/chat/messages", response_model=TasteAgentMessagesResponse)
def list_messages(user_id: str | None = None) -> TasteAgentMessagesResponse:
    return TasteAgentMessagesResponse(
        user_id=user_id,
        messages=restaurant_store.list_messages(user_id),
    )


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

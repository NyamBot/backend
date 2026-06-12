from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

import httpx

from app.core.config import settings
from app.schemas import RestaurantRecommendation


class HuggingFaceChatError(RuntimeError):
    pass


@dataclass(frozen=True)
class RestaurantChatCompletion:
    answer: str
    title: str | None = None


class HuggingFaceChatService:
    def __init__(self) -> None:
        self.base_url = settings.huggingface_chat_base_url.rstrip("/")
        self.model = settings.huggingface_chat_model
        self.timeout_seconds = settings.huggingface_chat_timeout_seconds

    @property
    def api_token(self) -> str | None:
        return settings.hf_token or settings.huggingface_api_token

    @property
    def configured(self) -> bool:
        return bool(self.api_token)

    def generate_restaurant_answer(
        self,
        query: str,
        recommendations: list[RestaurantRecommendation],
        fallback: bool,
        requested_area: str | None = None,
        area_filter: str | None = None,
    ) -> RestaurantChatCompletion | None:
        if not self.configured:
            return None

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "너는 NyamBot의 맛집 추천 에이전트야. "
                        "너의 역할은 새 식당을 찾는 것이 아니라, 백엔드가 이미 고른 후보를 사용자 요청에 맞게 설명하는 것이야. "
                        "후보 목록에 없는 식당, 메뉴, 영업시간, 휴무일, 웨이팅 정보를 지어내지 마. "
                        "후보 순서를 바꾸지 말고 1번을 1순위, 2번을 2순위, 3번을 3순위로 유지해. "
                        "저장 기록 후보와 카카오 장소 검색 후보를 구분해서 말해. "
                        "카카오 장소 검색 후보는 저장된 기록이 있다고 표현하지 마. "
                        "한국어로 짧고 친근하게 답해. "
                        "Markdown 문법을 쓰지 마. 별표, 굵은 글씨, 이모지는 사용하지 마."
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        'Return only JSON in this exact shape: {"answer":"...","title":"..."}. '
                        "The title must be Korean, natural, and under 24 characters. "
                        "Make the title a short topic phrase, not a copied user command. "
                        "Avoid request verbs like 찾아줘, 추천해줘, 골라줘, 알려줘. "
                        "Do not wrap the JSON in Markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_prompt(query, recommendations, fallback, requested_area, area_filter),
                },
            ],
            "temperature": 0.2,
            "max_tokens": 700,
        }

        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = error.response.text[:500] if error.response is not None else str(error)
            raise HuggingFaceChatError(detail) from error
        except httpx.HTTPError as error:
            raise HuggingFaceChatError(str(error)) from error

        data = response.json()
        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise HuggingFaceChatError("Hugging Face chat response format is invalid") from error
        return self._parse_answer_response(str(answer))

    def rerank_restaurant_candidates(
        self,
        query: str,
        recommendations: list[RestaurantRecommendation],
        requested_area: str | None = None,
        area_filter: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        if not self.configured or not recommendations:
            return []

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "너는 맛집 후보를 재정렬하는 랭킹 에이전트야. "
                        "반드시 후보 목록 안에서만 고르고, 후보 밖 식당은 만들지 마. "
                        "사용자 발화의 숨은 의도를 분석해서 후보를 고르되, 지역 조건은 반드시 지켜. "
                        "현재 위치와 후보별 거리 정보가 있으면 가까운 후보를 더 유리하게 봐. "
                        "응답은 설명 문장 없이 JSON 객체 하나만 반환해."
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_rerank_prompt(
                        query,
                        recommendations,
                        requested_area,
                        area_filter,
                        latitude,
                        longitude,
                        limit,
                    ),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 900,
        }

        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = error.response.text[:500] if error.response is not None else str(error)
            raise HuggingFaceChatError(detail) from error
        except httpx.HTTPError as error:
            raise HuggingFaceChatError(str(error)) from error

        data = response.json()
        try:
            content = str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as error:
            raise HuggingFaceChatError("Hugging Face rerank response format is invalid") from error
        return self._parse_rerank_response(content)

    def _build_prompt(
        self,
        query: str,
        recommendations: list[RestaurantRecommendation],
        fallback: bool,
        requested_area: str | None,
        area_filter: str | None,
    ) -> str:
        if not recommendations:
            return (
                f"사용자 요청: {query}\n"
                "저장된 맛집 후보가 없습니다. 저장된 맛집을 더 등록하면 추천할 수 있다고 안내해줘."
            )

        mode = (
            "저장 맛집 후보가 부족해서 카카오 장소 검색 후보가 포함되어 있습니다."
            if fallback
            else "사용자의 저장 맛집 후보만 사용 중입니다."
        )
        lines = [
            f"사용자 요청: {query}",
            f"요청 지역: {requested_area or '명시 없음'}",
            f"백엔드 지역 필터: {area_filter or '없음'}",
            mode,
            "",
            "중요 규칙:",
            "- 아래 후보 목록만 사용해. 후보 밖 식당은 절대 말하지 마.",
            "- 후보 순서를 그대로 유지해. 점수를 다시 매기거나 순위를 바꾸지 마.",
            "- 요청 지역이 있으면 지역 조건을 가장 중요한 기준으로 설명해.",
            "- 사용자가 혼밥, 데이트, 회식처럼 상황을 말하면 그 상황과 맞는 이유를 근거 안에서만 설명해.",
            "- 근거가 카카오 장소 검색이면 저장 메모라고 말하지 마.",
            "- 영업시간, 휴무, 웨이팅은 확인이 필요하다고만 말하고 구체 값을 지어내지 마.",
            "",
            "후보 목록:",
        ]
        for index, recommendation in enumerate(recommendations, start=1):
            restaurant = recommendation.restaurant
            evidence = " / ".join(recommendation.evidence) or "근거 기록 없음"
            source_type = "카카오 장소 검색 후보" if restaurant.id.startswith("kakao-") or restaurant.note_count == 0 else "저장 맛집 기록 후보"
            meta = " / ".join(part for part in (restaurant.area, restaurant.cuisine, restaurant.price_level) if part)
            lines.extend(
                [
                    f"{index}. {restaurant.name}",
                    f"- 후보 출처: {source_type}",
                    f"- 지역/종류/가격: {meta}",
                    f"- 분위기 태그: {', '.join(restaurant.mood_tags) or '없음'}",
                    f"- 추천 점수: {recommendation.score}",
                    f"- 기존 추천 이유: {recommendation.reason}",
                    f"- 근거 기록: {evidence}",
                    f"- 카카오 링크: {restaurant.kakao_place_url or '없음'}",
                ]
            )
        lines.extend(
            [
                "",
                "답변 형식:",
                "- 첫 문장에 가장 잘 맞는 후보를 말해줘.",
                "- 최대 3개까지 번호 목록으로 추천해줘.",
                "- 각 후보마다 왜 맞는지와 근거를 한두 문장으로 짧게 적어줘.",
                "- 카카오 후보라면 '저장된 기록' 대신 '장소 검색 기준 후보'라고 말해줘.",
                "- 마지막에 영업시간/휴무는 방문 전에 확인하라고 한 번만 안내해줘.",
                "- 별표나 굵은 글씨 같은 Markdown 문법은 절대 쓰지 마.",
                "- 이모지는 쓰지 마.",
            ]
        )
        return "\n".join(lines)

    def _build_rerank_prompt(
        self,
        query: str,
        recommendations: list[RestaurantRecommendation],
        requested_area: str | None,
        area_filter: str | None,
        latitude: float | None,
        longitude: float | None,
        limit: int,
    ) -> str:
        candidates = []
        for index, recommendation in enumerate(recommendations, start=1):
            restaurant = recommendation.restaurant
            source_type = "kakao" if restaurant.id.startswith("kakao-") or restaurant.note_count == 0 else "saved"
            candidates.append(
                {
                    "candidate_id": restaurant.id,
                    "index": index,
                    "source": source_type,
                    "name": restaurant.name,
                    "area": restaurant.area,
                    "cuisine": restaurant.cuisine,
                    "price_level": restaurant.price_level,
                    "mood_tags": restaurant.mood_tags,
                    "address": restaurant.road_address or restaurant.address,
                    "latitude": restaurant.latitude,
                    "longitude": restaurant.longitude,
                    "note_count": restaurant.note_count,
                    "evidence": recommendation.evidence,
                    "base_score": recommendation.score,
                }
            )

        payload = {
            "user_query": query,
            "requested_area": requested_area,
            "backend_area_filter": area_filter,
            "current_location": (
                {"latitude": latitude, "longitude": longitude}
                if latitude is not None and longitude is not None
                else None
            ),
            "selection_count": limit,
            "rules": [
                "candidate_id는 candidates 안의 값만 사용한다.",
                "지역 조건이 있으면 그 지역과 맞는 후보만 고른다.",
                "사용자 발화에서 상황, 분위기, 가격감, 식사 강도, 제외 의도를 추론한다.",
                "혼밥, 간단히, 출출함, 데이트, 회식 같은 표현은 후보 선택 이유에 반영한다.",
                "혼밥, 출출함, 한 끼, 식사, 밥처럼 실제 식사를 뜻하는 요청이면 카페/디저트/커피 후보보다 밥집, 한식, 일식, 분식, 면, 덮밥, 돈까스, 라멘 같은 식사 후보를 우선한다.",
                "사용자가 카페를 직접 원하지 않았고 식사 후보가 충분하면 카페 후보는 선택하지 않는다.",
                "카카오 후보도 저장 후보처럼 말하지 말고 source를 고려한다.",
                "반드시 JSON만 반환한다.",
            ],
            "response_schema": {
                "intent_summary": "string",
                "ranked_candidates": [
                    {
                        "candidate_id": "string",
                        "rank": 1,
                        "reason": "string",
                    }
                ],
            },
            "candidates": candidates,
        }
        return json.dumps(payload, ensure_ascii=False)

    def _parse_rerank_response(self, content: str) -> list[dict[str, Any]]:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise HuggingFaceChatError("Hugging Face rerank response is not valid JSON") from error
        ranked = parsed.get("ranked_candidates") if isinstance(parsed, dict) else None
        if not isinstance(ranked, list):
            raise HuggingFaceChatError("Hugging Face rerank response has no ranked_candidates")
        return [item for item in ranked if isinstance(item, dict)]

    def _parse_answer_response(self, content: str) -> RestaurantChatCompletion | None:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)

        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            answer = self._clean_answer(content)
            return RestaurantChatCompletion(answer=answer) if answer else None

        if not isinstance(parsed, dict):
            answer = self._clean_answer(content)
            return RestaurantChatCompletion(answer=answer) if answer else None

        answer = self._clean_answer(str(parsed.get("answer") or ""))
        if not answer:
            return None
        title = self._clean_title(str(parsed.get("title") or ""))
        return RestaurantChatCompletion(answer=answer, title=title)

    def _clean_answer(self, answer: str) -> str:
        return (
            answer.replace("**", "")
            .replace("__", "")
            .replace("*", "")
            .strip()
        )

    def _clean_title(self, title: str) -> str | None:
        cleaned = re.sub(r"\s+", " ", title).strip(" \t\r\n\"'`")
        if not cleaned:
            return None
        return cleaned[:24]


huggingface_chat_service = HuggingFaceChatService()

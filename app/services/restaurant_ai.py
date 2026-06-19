from __future__ import annotations

from dataclasses import dataclass
import json
import random
import re
from typing import Any

import httpx

from app.core.config import settings
from app.schemas import RestaurantRecommendation


class RestaurantAiError(RuntimeError):
    pass


@dataclass(frozen=True)
class RestaurantChatCompletion:
    answer: str
    title: str | None = None


@dataclass(frozen=True)
class RerankCandidate:
    candidate_id: str
    text: str


class RestaurantAiService:
    def __init__(self) -> None:
        self.base_url = settings.huggingface_chat_base_url.rstrip("/")
        self.model = settings.gemma_chat_model
        self.timeout_seconds = settings.huggingface_chat_timeout_seconds
        self.rerank_enabled = settings.huggingface_rerank_enabled
        self.rerank_base_url = settings.huggingface_rerank_base_url.rstrip("/")
        self.rerank_model = settings.huggingface_rerank_model
        self.rerank_timeout_seconds = settings.huggingface_rerank_timeout_seconds

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
                        "사용자 요청이 맛집, 식사, 음식, 카페, 장소 추천과 무관하면 식당 추천을 억지로 하지 말고, 맛집 추천 질문으로 다시 물어봐. "
                        "후보 목록에 없는 식당, 메뉴, 영업시간, 휴무일, 웨이팅 정보를 지어내지 마. "
                        "후보 순서를 바꾸지 말고 1번을 1순위, 2번을 2순위, 3번을 3순위로 유지해. "
                        "저장 기록 후보는 저장 메모와 취향 근거를 중심으로 설명해. "
                        "장소 검색 후보는 저장된 기록이 있다고 표현하지 말고, 지역, 업종, 거리, 접근성처럼 확인 가능한 특징만 자연스럽게 설명해. "
                        "답변에서 카카오, 장소 검색, 백엔드, 후보 출처 같은 내부 출처 표현은 반복하지 마. "
                        "같은 질문이 반복되어도 첫 문장, 표현, 근거를 매번 조금 다르게 말해. "
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
            "temperature": 0.55,
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
            raise RestaurantAiError(detail) from error
        except httpx.HTTPError as error:
            raise RestaurantAiError(str(error)) from error

        data = response.json()
        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RestaurantAiError("Hugging Face chat response format is invalid") from error
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
        if not self.configured or not self.rerank_enabled or not recommendations:
            return []

        candidates = self._build_rerank_candidates(recommendations)
        rerank_query = self._build_rerank_query(query, requested_area, area_filter, latitude, longitude)
        payload = {
            "inputs": [
                {"text": rerank_query, "text_pair": candidate.text}
                for candidate in candidates
            ]
        }

        try:
            response = httpx.post(
                f"{self.rerank_base_url}/{self.rerank_model}",
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.rerank_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = error.response.text[:500] if error.response is not None else str(error)
            raise RestaurantAiError(detail) from error
        except httpx.HTTPError as error:
            raise RestaurantAiError(str(error)) from error

        return self._parse_rerank_scores(response.json(), candidates, limit)

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
            "저장 맛집 후보가 부족해서 외부 장소 후보가 포함되어 있습니다. 이 정보는 내부 판단용이며 답변에 그대로 쓰지 마세요."
            if fallback
            else "사용자의 저장 맛집 후보만 사용 중입니다."
        )
        lines = [
            f"사용자 요청: {query}",
            f"요청 지역: {requested_area or '명시 없음'}",
            f"백엔드 지역 필터: {area_filter or '없음'}",
            f"답변 변주 키: {random.randint(1000, 9999)}",
            mode,
            "",
            "중요 규칙:",
            "- 아래 후보 목록만 사용해. 후보 밖 식당은 절대 말하지 마.",
            "- 후보 순서를 그대로 유지해. 점수를 다시 매기거나 순위를 바꾸지 마.",
            "- 같은 사용자 요청이라도 답변 변주 키에 맞춰 첫 문장과 표현을 조금 다르게 써.",
            "- 사용자 요청이 맛집/식사/음식/카페/장소 추천과 무관하면 후보를 추천하지 말고, 맛집 추천 질문으로 다시 물어봐.",
            "- 요청 지역이 있으면 지역 조건을 가장 중요한 기준으로 설명해.",
            "- 사용자가 혼밥, 데이트, 회식처럼 상황을 말하면 그 상황과 맞는 이유를 근거 안에서만 설명해.",
            "- 후보 출처는 내부 판단용이야. 답변에는 카카오, 장소 검색, 백엔드 같은 출처 표현을 쓰지 마.",
            "- 저장 맛집 기록 후보는 저장 메모를 근거로 설명해.",
            "- 외부 장소 후보는 저장 메모라고 말하지 말고, 지역/종류/거리/접근성/요청 상황 적합성으로 설명해.",
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
                    f"- 판단 힌트: {recommendation.reason}",
                    f"- 저장 메모 또는 장소 특징: {evidence}",
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
                "- 저장 메모가 없는 후보는 출처를 말하지 말고, 확인 가능한 장소 특징만 근거처럼 풀어줘.",
                "- 마지막에 영업시간/휴무는 방문 전에 확인하라고 한 번만 안내해줘.",
                "- 별표나 굵은 글씨 같은 Markdown 문법은 절대 쓰지 마.",
                "- 이모지는 쓰지 마.",
            ]
        )
        return "\n".join(lines)

    def _build_rerank_query(
        self,
        query: str,
        requested_area: str | None,
        area_filter: str | None,
        latitude: float | None,
        longitude: float | None,
    ) -> str:
        location = (
            f"현재 위치 위도 {latitude}, 경도 {longitude}"
            if latitude is not None and longitude is not None
            else "현재 위치 없음"
        )
        return (
            f"사용자 맛집 추천 요청: {query}\n"
            f"요청 지역: {requested_area or '명시 없음'}\n"
            f"백엔드 지역 필터: {area_filter or '없음'}\n"
            f"{location}\n"
            "식사 의도, 음식 종류, 분위기, 가격대, 지역 일치, 거리 정보를 기준으로 가장 관련 있는 식당 후보를 골라줘. "
            "사용자가 카페를 직접 요청하지 않았다면 밥집/식사 후보를 더 관련 있게 봐줘."
        )

    def _build_rerank_candidates(
        self,
        recommendations: list[RestaurantRecommendation],
    ) -> list[RerankCandidate]:
        candidates = []
        for recommendation in recommendations:
            restaurant = recommendation.restaurant
            source_type = "kakao" if restaurant.id.startswith("kakao-") or restaurant.note_count == 0 else "saved"
            evidence = " / ".join(recommendation.evidence) or "근거 기록 없음"
            address = restaurant.road_address or restaurant.address or "주소 없음"
            text = "\n".join(
                [
                    f"식당명: {restaurant.name}",
                    f"출처: {source_type}",
                    f"지역: {restaurant.area}",
                    f"상세 지역: {' '.join(part for part in (restaurant.city, restaurant.district, restaurant.town) if part) or '없음'}",
                    f"주소: {address}",
                    f"음식 종류: {restaurant.cuisine}",
                    f"가격대: {restaurant.price_level}",
                    f"분위기 태그: {', '.join(restaurant.mood_tags) or '없음'}",
                    f"대표 메뉴: {', '.join(restaurant.signature_menus) or '없음'}",
                    f"판단 힌트: {recommendation.reason}",
                    f"근거: {evidence}",
                    f"기본 점수: {recommendation.score}",
                ]
            )
            candidates.append(RerankCandidate(candidate_id=restaurant.id, text=text))
        return candidates

    def _parse_rerank_scores(
        self,
        data: Any,
        candidates: list[RerankCandidate],
        limit: int,
    ) -> list[dict[str, Any]]:
        scores = self._extract_rerank_scores(data, len(candidates))
        if not scores:
            raise RestaurantAiError("Hugging Face rerank response format is invalid")

        ranked = sorted(scores, key=lambda item: item[1], reverse=True)[:limit]
        return [
            {
                "candidate_id": candidates[index].candidate_id,
                "rank": rank,
                "score": score,
            }
            for rank, (index, score) in enumerate(ranked, start=1)
            if 0 <= index < len(candidates)
        ]

    def _extract_rerank_scores(self, data: Any, candidate_count: int) -> list[tuple[int, float]]:
        if isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list):
                scores = []
                for fallback_index, item in enumerate(results):
                    if not isinstance(item, dict):
                        continue
                    index = self._as_int(item.get("index"), fallback_index)
                    score = self._as_float(item.get("relevance_score", item.get("score")))
                    if score is not None:
                        scores.append((index, score))
                return scores
            if "output" in data:
                return self._extract_rerank_scores(data["output"], candidate_count)

        if isinstance(data, list):
            if len(data) == 1 and isinstance(data[0], list):
                batch_scores = [
                    self._as_float(item.get("score"))
                    for item in data[0][:candidate_count]
                    if isinstance(item, dict)
                ]
                if len(batch_scores) == min(candidate_count, len(data[0])):
                    return [
                        (index, score)
                        for index, score in enumerate(batch_scores)
                        if score is not None
                    ]

            if all(isinstance(item, dict) and "index" in item for item in data):
                scores = []
                for fallback_index, item in enumerate(data):
                    index = self._as_int(item.get("index"), fallback_index)
                    score = self._as_float(item.get("relevance_score", item.get("score")))
                    if score is not None:
                        scores.append((index, score))
                return scores

            scores = []
            for index, item in enumerate(data[:candidate_count]):
                score = self._extract_text_classification_score(item)
                if score is not None:
                    scores.append((index, score))
            return scores

        return []

    def _extract_text_classification_score(self, item: Any) -> float | None:
        if isinstance(item, list):
            label_scores = [
                entry
                for entry in item
                if isinstance(entry, dict) and self._as_float(entry.get("score")) is not None
            ]
            if not label_scores:
                return None
            positive = [
                entry
                for entry in label_scores
                if str(entry.get("label", "")).upper() in {"LABEL_1", "POSITIVE", "RELEVANT"}
            ]
            selected = positive[0] if positive else max(label_scores, key=lambda entry: self._as_float(entry.get("score")) or 0)
            return self._as_float(selected.get("score"))

        if isinstance(item, dict):
            return self._as_float(item.get("relevance_score", item.get("score")))

        return None

    def _as_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _as_float(self, value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

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


restaurant_ai_service = RestaurantAiService()

from __future__ import annotations

import httpx

from app.core.config import settings


class HuggingFaceGenerationService:
    def __init__(self) -> None:
        self.model = settings.hf_text_model
        self.token = settings.hf_api_token
        self.enabled = bool(settings.use_hf_generation and self.token)

    def generate(self, prompt: str, max_new_tokens: int = 500) -> str | None:
        if not self.enabled:
            return None

        url = f"https://api-inference.huggingface.co/models/{self.model}"
        headers = {"Authorization": f"Bearer {self.token}"}
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": max_new_tokens,
                "return_full_text": False,
                "temperature": 0.4,
            },
        }

        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None

        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0].get("generated_text")
        if isinstance(data, dict):
            return data.get("generated_text")
        return None


hf_generation = HuggingFaceGenerationService()

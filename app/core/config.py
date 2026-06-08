import os

from pydantic_settings import BaseSettings, SettingsConfigDict


APP_ENV = os.getenv("APP_ENV", "dev")


class Settings(BaseSettings):
    app_name: str = "NyamBot"
    app_env: str = "dev"
    database_url: str = "sqlite:///./data/nyambot.db"
    frontend_url: str = "http://localhost:5173"
    kakao_client_id: str | None = None
    kakao_client_secret: str | None = None
    kakao_local_rest_api_key: str | None = None
    kakao_redirect_uri: str = "http://localhost:8000/api/auth/kakao/callback"
    jwt_secret_key: str | None = None
    hf_token: str | None = None
    huggingface_api_token: str | None = None
    huggingface_chat_base_url: str = "https://router.huggingface.co/v1"
    huggingface_chat_model: str = "google/gemma-4-26B-A4B-it:featherless-ai"
    huggingface_chat_timeout_seconds: float = 20.0

    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{APP_ENV}"),
        env_file_encoding="utf-8",
    )


settings = Settings()

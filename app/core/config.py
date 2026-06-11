import os

from pydantic_settings import BaseSettings, SettingsConfigDict


APP_ENV = os.getenv("APP_ENV", "dev")


class Settings(BaseSettings):
    app_name: str = "NyamBot"
    app_env: str = "dev"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./data/nyambot.db"
    frontend_url: str = "http://127.0.0.1:5173"
    kakao_client_id: str | None = None
    kakao_client_secret: str | None = None
    kakao_local_rest_api_key: str | None = None
    kakao_redirect_uri: str = "http://127.0.0.1:8000/api/v1/auth/kakao/callback"
    jwt_secret_key: str | None = None
    hf_token: str | None = None
    huggingface_api_token: str | None = None
    huggingface_chat_base_url: str = "https://router.huggingface.co/v1"
    huggingface_chat_model: str = "google/gemma-4-26B-A4B-it:featherless-ai"
    huggingface_chat_timeout_seconds: float = 20.0
    chat_message_backend: str = "opensearch"
    opensearch_url: str = "http://127.0.0.1:9200"
    opensearch_username: str | None = None
    opensearch_password: str | None = None
    opensearch_chat_messages_index: str = "nyambot-chat-messages"
    opensearch_verify_certs: bool = False

    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{APP_ENV}"),
        env_file_encoding="utf-8",
    )


settings = Settings()

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


APP_ENV = os.getenv("APP_ENV", "dev")


class Settings(BaseSettings):
    app_name: str = "TasteForge AI"
    app_env: str = "dev"
    database_url: str = "sqlite:///./data/tasteforge.db"
    frontend_url: str = "http://localhost:5173"
    kakao_client_id: str | None = None
    kakao_client_secret: str | None = None
    kakao_local_rest_api_key: str | None = None
    kakao_redirect_uri: str = "http://localhost:8000/api/auth/kakao/callback"
    jwt_secret_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{APP_ENV}"),
        env_file_encoding="utf-8",
    )


settings = Settings()

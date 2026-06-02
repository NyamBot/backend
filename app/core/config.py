from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ClipForge AI"
    app_env: str = "dev"
    database_url: str = "sqlite:///./data/clipforge.db"
    hf_api_token: str | None = None
    hf_text_model: str = "Qwen/Qwen2.5-7B-Instruct"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    use_hf_generation: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()

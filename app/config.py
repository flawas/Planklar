from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfiguration ausschliesslich aus Umgebungsvariablen."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+psycopg://planklar:planklar@localhost:5432/planklar"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    llm_model: str = ""
    llm_api_key: str = ""
    retention_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfiguration ausschliesslich aus Umgebungsvariablen."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+psycopg://liquet:liquet@localhost:5432/liquet"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "liquet"
    s3_region: str = "us-east-1"
    signed_url_ttl_seconds: int = 300
    max_upload_bytes: int = 100 * 1024 * 1024
    llm_model: str = ""
    llm_api_key: str = ""
    git_commit: str = "unbekannt"
    retention_days: int = 30
    auth_secret: str = ""
    auth_cookie_secure: bool = True
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_session_seconds: int = 8 * 3600
    oidc_enabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()

import pytest

from app.config import Settings

KEYS = ["DATABASE_URL", "REDIS_URL", "S3_ENDPOINT", "LLM_MODEL", "LLM_API_KEY", "RETENTION_DAYS"]


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    assert settings.redis_url.startswith("redis://")
    assert settings.retention_days == 30
    assert settings.llm_api_key == ""


def test_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("REDIS_URL", "redis://r:1/2")
    monkeypatch.setenv("S3_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("RETENTION_DAYS", "7")
    settings = Settings()
    assert settings.database_url == "postgresql://x/y"
    assert settings.redis_url == "redis://r:1/2"
    assert settings.s3_endpoint == "http://minio:9000"
    assert settings.llm_model == "m"
    assert settings.llm_api_key == "k"
    assert settings.retention_days == 7

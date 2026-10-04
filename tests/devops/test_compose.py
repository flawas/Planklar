from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_web_runs_migrations_before_uvicorn() -> None:
    cmd = "alembic upgrade head && python -m app.db.app_role && exec uvicorn app.main:app"
    assert cmd in COMPOSE


def test_alembic_config_in_image() -> None:
    assert "COPY --chown=liquet:liquet alembic.ini ./alembic.ini" in DOCKERFILE
    assert (ROOT / "alembic.ini").is_file()


def test_proxy_vor_web_mit_festen_tags() -> None:
    assert "image: caddy:" in COMPOSE
    assert (ROOT / "Caddyfile").is_file()
    assert "reverse_proxy web:8000" in (ROOT / "Caddyfile").read_text(encoding="utf-8")
    assert ":latest" not in COMPOSE


def test_env_example_ohne_secrets() -> None:
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "AUTH_SECRET=change-me" in env
    assert "LLM_API_KEY=\n" in env


def test_s3_zugangsdaten_fuer_app_und_speicher() -> None:
    assert "S3_ACCESS_KEY: ${S3_ACCESS_KEY:-liquet}" in COMPOSE
    assert "AWS_ACCESS_KEY_ID: ${S3_ACCESS_KEY:-liquet}" in COMPOSE

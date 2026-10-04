from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_web_runs_migrations_before_uvicorn() -> None:
    cmd = "alembic upgrade head && exec uvicorn app.main:app"
    assert cmd in COMPOSE


def test_alembic_config_in_image() -> None:
    assert "COPY --chown=liquet:liquet alembic.ini ./alembic.ini" in DOCKERFILE
    assert (ROOT / "alembic.ini").is_file()

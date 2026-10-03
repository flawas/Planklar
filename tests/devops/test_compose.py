import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


def test_expected_services() -> None:
    assert set(SERVICES) == {"proxy", "web", "worker", "db", "redis", "minio"}


def test_restart_policy_everywhere() -> None:
    for name, svc in SERVICES.items():
        assert svc["restart"] == "unless-stopped", name


def test_images_have_fixed_tags() -> None:
    for name, svc in SERVICES.items():
        image = svc["image"]
        if name in {"web", "worker"}:
            continue  # Tag kommt aus ${TAG}, Default `dev`
        assert ":" in image and not image.endswith(":latest"), name


def test_app_image_is_shared() -> None:
    assert SERVICES["web"]["image"] == SERVICES["worker"]["image"]
    assert ":latest" not in SERVICES["web"]["image"]


def test_healthchecks() -> None:
    for name in ("web", "db", "redis", "minio"):
        assert SERVICES[name]["healthcheck"]["test"], name


def test_web_runs_migrations_then_uvicorn() -> None:
    cmd = " ".join(SERVICES["web"]["command"])
    assert cmd.index("alembic upgrade head") < cmd.index("uvicorn app.main:app")


def test_worker_command() -> None:
    assert SERVICES["worker"]["command"][:4] == ["celery", "-A", "app.worker", "worker"]


def test_caddy_proxies_to_web() -> None:
    assert "reverse_proxy web:8000" in (ROOT / "Caddyfile").read_text(encoding="utf-8")


def test_env_example_has_only_placeholders() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert not re.search(r"(sk-|AKIA|ghp_)", text)
    for key in ("DATABASE_URL", "REDIS_URL", "S3_ENDPOINT", "AUTH_SECRET", "POSTGRES_PASSWORD"):
        assert re.search(rf"^{key}=", text, re.M), key

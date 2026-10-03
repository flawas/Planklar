import pytest

from app.worker import celery_app, ping


@pytest.fixture
def eager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    monkeypatch.setattr(celery_app.conf, "task_store_eager_result", False)


def test_ping_eager(eager: None) -> None:
    assert ping.delay().get() == "pong"


def test_broker_from_redis_url() -> None:
    assert celery_app.conf.broker_url.startswith("redis://")

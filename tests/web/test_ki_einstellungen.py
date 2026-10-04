import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import KiEinstellung
from app.pipeline import llm, llm_config
from app.pipeline.llm import FakeLLMClient
from tests.auth.conftest import make_user
from tests.web.test_login import do_login

URL = "/einstellungen/ki"


def token(client: TestClient) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', client.get(URL).text)
    assert m
    return m.group(1)


@pytest.fixture
def admin(client: TestClient, db: Session) -> str:
    make_user(db, "admin@buero-a.ch", superuser=True)
    do_login(client, "admin@buero-a.ch")
    return token(client)


def speichern(client: TestClient, tok: str, **data: str):  # type: ignore[no-untyped-def]
    return client.post(URL, data={"csrf_token": tok, **data})


def test_nur_superuser(client: TestClient, db: Session) -> None:
    make_user(db, "user@buero-a.ch")
    do_login(client, "user@buero-a.ch")
    assert client.get(URL).status_code == 404
    assert client.post(URL, data={"modell": "x"}).status_code == 404


def test_anonym_wird_zum_login_geleitet(client: TestClient, db: Session) -> None:
    r = client.get(URL, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_speichern_verschluesselt_key(client: TestClient, db: Session, admin: str) -> None:
    r = speichern(client, admin, modell="anthropic/claude-sonnet-5-5", api_key="sk-geheim-123")
    assert r.status_code == 200 and "Einstellungen gespeichert." in r.text
    assert "sk-geheim-123" not in r.text and "Hinterlegt" in r.text
    row = db.get(KiEinstellung, 1)
    assert row and row.modell == "anthropic/claude-sonnet-5-5"
    assert "sk-geheim-123" not in row.api_key_verschluesselt
    cfg = llm_config.load_config(db)
    assert cfg.api_key == "sk-geheim-123" and cfg.model == "anthropic/claude-sonnet-5-5"


def test_leerer_key_behaelt_bestehenden_und_entfernen(
    client: TestClient, db: Session, admin: str
) -> None:
    speichern(client, admin, modell="m", api_key="sk-1")
    speichern(client, admin, modell="m2", api_base="https://eu.api.openai.com/v1")
    cfg = llm_config.load_config(db)
    assert cfg.api_key == "sk-1" and cfg.model == "m2" and cfg.api_base.startswith("https://eu.")
    speichern(client, admin, modell="m2", clear_key="1")
    db.expire_all()
    assert llm_config.load_config(db).api_key == ""


def test_validierung(client: TestClient, db: Session, admin: str) -> None:
    assert speichern(client, admin, modell="").status_code == 422
    r = speichern(client, admin, modell="m", api_base="http://unsicher")
    assert r.status_code == 422 and "https://" in r.text
    assert db.get(KiEinstellung, 1) is None


def test_csrf(client: TestClient, db: Session, admin: str) -> None:
    assert speichern(client, "falsch", modell="m").status_code == 403
    assert db.get(KiEinstellung, 1) is None


def test_env_als_fallback(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("LLM_MODEL", "env-modell")
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    get_settings.cache_clear()
    cfg = llm_config.load_config(db)
    assert (cfg.model, cfg.api_key) == ("env-modell", "env-key")


def test_verbindungstest(
    client: TestClient, db: Session, admin: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = client.post(URL + "/test", data={"csrf_token": admin})
    assert "Zuerst ein Modell speichern." in r.text
    speichern(client, admin, modell="m")
    monkeypatch.setattr(llm, "_default_client_factory", lambda: FakeLLMClient([{"ok": True}]))
    assert "Verbindung erfolgreich." in client.post(URL + "/test", data={"csrf_token": admin}).text
    monkeypatch.setattr(llm, "_default_client_factory", lambda: FakeLLMClient([]))
    assert (
        "Verbindung fehlgeschlagen." in client.post(URL + "/test", data={"csrf_token": admin}).text
    )

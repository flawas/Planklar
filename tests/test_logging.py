import json
import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.logging_setup import configure_logging, install_request_logging, log_event


def _records(caplog: pytest.LogCaptureFixture) -> list[dict]:
    from app.logging_setup import JsonFormatter

    fmt = JsonFormatter()
    return [json.loads(fmt.format(r)) for r in caplog.records if r.name == "planklar"]


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    install_request_logging(app)

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"a": "b"}

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("Hans Muster, Bahnhofstrasse 1")

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _propagate() -> None:
    configure_logging()
    logging.getLogger("planklar").propagate = True


def test_request_logged_with_id_duration(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="planklar")
    response = client.get("/ok")
    rec = _records(caplog)[-1]
    assert rec["event"] == "request"
    assert rec["request_id"] == response.headers["X-Request-ID"]
    uuid.UUID(rec["request_id"])
    assert rec["duration_ms"] >= 0
    assert rec["status"] == 200


def test_error_code_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="planklar")
    client.get("/missing")
    assert _records(caplog)[-1]["error_code"] == "http_404"


def test_log_event_rejects_free_text() -> None:
    with pytest.raises(ValueError):
        log_event("x", note="Hans Muster wohnt hier")
    with pytest.raises(ValueError):
        log_event("x", dossier_id="Freitext mit Leerzeichen")
    with pytest.raises(ValueError):
        log_event("x", content=b"%PDF-1.7")
    with pytest.raises(ValueError):
        log_event("x", error_code="Freitext mit Leerzeichen")
    for key in ("valid", "paid", "void", "barcode"):
        with pytest.raises(ValueError):
            log_event("x", **{key: "Muster"})


def test_log_event_accepts_ids_and_codes(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="planklar")
    did = uuid.uuid4()
    log_event("done", dossier_id=did, error_code="E_X", pages=3)
    rec = _records(caplog)[-1]
    assert rec["dossier_id"] == str(did)
    assert rec["pages"] == 3


def test_unhandled_exception_logs_type_not_message(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="planklar")
    response = client.get("/boom")
    assert response.status_code == 500
    rid = response.headers["X-Request-ID"]
    assert response.json()["request_id"] == rid
    text = json.dumps(_records(caplog))
    assert "Hans Muster" not in text and "Bahnhofstrasse" not in text
    rec = next(r for r in _records(caplog) if r["event"] == "unhandled_exception")
    assert rec["exception_code"] == "RuntimeError"
    assert rec["request_id"] == rid

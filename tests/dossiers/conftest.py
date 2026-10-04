from collections.abc import Iterator

import pymupdf
import pytest
from moto import mock_aws

from app.config import Settings
from app.dossiers.service import get_storage
from app.main import app
from app.storage import Storage
from tests.auth.conftest import _auth_env, client, db  # noqa: F401  (Fixtures wiederverwenden)


def make_pdf(pages: int = 1, text: str = "Testplan") -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"{text} {i}")
    data: bytes = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def storage() -> Iterator[Storage]:
    with mock_aws():
        store = Storage(
            Settings(s3_endpoint="", s3_bucket="test-bucket", s3_access_key="k", s3_secret_key="s")
        )
        store.ensure_bucket()
        app.dependency_overrides[get_storage] = lambda: store
        yield store
        app.dependency_overrides.pop(get_storage, None)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.dossiers.router.run_pruefung_task.delay",
        lambda buero_id, pruefung_id: calls.append((buero_id, pruefung_id)),
    )
    return calls

from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from app.config import Settings
from app.storage import ObjectNotFoundError, Storage, object_key

SHA = "a" * 64


@pytest.fixture
def storage() -> Iterator[Storage]:
    with mock_aws():
        settings = Settings(
            s3_endpoint="",
            s3_bucket="test-bucket",
            s3_access_key="k",
            s3_secret_key="s",
            signed_url_ttl_seconds=60,
        )
        store = Storage(settings)
        store.ensure_bucket()
        yield store


def test_object_key() -> None:
    assert object_key(1, 2, SHA) == f"buero/1/dossier/2/{SHA}.pdf"


def test_object_key_rejects_invalid_hash() -> None:
    with pytest.raises(ValueError):
        object_key(1, 2, "../x")


@pytest.mark.parametrize("bad", ["1/dossier/2", "../x", "", "-1", "1 ", True, 1.5])
def test_object_key_rejects_malicious_ids(bad: Any) -> None:
    with pytest.raises(ValueError):
        object_key(bad, 2, SHA)
    with pytest.raises(ValueError):
        object_key(1, bad, SHA)


def test_put_get_roundtrip(storage: Storage) -> None:
    key = storage.put(1, 2, SHA, b"%PDF-1.7")
    assert key == f"buero/1/dossier/2/{SHA}.pdf"
    assert storage.get(1, 2, SHA) == b"%PDF-1.7"


def test_get_missing(storage: Storage) -> None:
    with pytest.raises(ObjectNotFoundError):
        storage.get(1, 2, SHA)


def test_other_buero_cannot_access(storage: Storage) -> None:
    storage.put(1, 2, SHA, b"geheim")
    with pytest.raises(ObjectNotFoundError):
        storage.get(2, 2, SHA)
    storage.delete(2, 2, SHA)
    assert storage.get(1, 2, SHA) == b"geheim"
    assert "buero/2/" in storage.signed_url(2, 2, SHA)
    assert "buero/1/" not in storage.signed_url(2, 2, SHA)


def test_access_rejects_malicious_ids(storage: Storage) -> None:
    with pytest.raises(ValueError):
        storage.get("1/dossier/2", 2, SHA)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        storage.delete(1, "../x", SHA)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        storage.signed_url("../x", 2, SHA)  # type: ignore[arg-type]


def test_delete(storage: Storage) -> None:
    storage.put(1, 2, SHA, b"x")
    storage.delete(1, 2, SHA)
    with pytest.raises(ObjectNotFoundError):
        storage.get(1, 2, SHA)


def test_ensure_bucket_idempotent(storage: Storage) -> None:
    storage.ensure_bucket()
    names = [b["Name"] for b in boto3.client("s3").list_buckets()["Buckets"]]
    assert names == ["test-bucket"]


def test_signed_url_uses_configured_ttl(storage: Storage) -> None:
    storage.put(1, 2, SHA, b"x")
    url = storage.signed_url(1, 2, SHA)
    assert object_key(1, 2, SHA) in url
    assert "X-Amz-Expires=60" in url
    assert "X-Amz-Expires=5" in storage.signed_url(1, 2, SHA, expires_in=5)


def test_signed_url_rejects_nonpositive_ttl(storage: Storage) -> None:
    with pytest.raises(ValueError):
        storage.signed_url(1, 2, SHA, expires_in=0)

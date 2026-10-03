from collections.abc import Iterator

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


def test_put_get_roundtrip(storage: Storage) -> None:
    key = object_key(1, 2, SHA)
    storage.put(key, b"%PDF-1.7")
    assert storage.get(key) == b"%PDF-1.7"


def test_get_missing(storage: Storage) -> None:
    with pytest.raises(ObjectNotFoundError):
        storage.get(object_key(1, 2, SHA))


def test_delete(storage: Storage) -> None:
    key = object_key(1, 2, SHA)
    storage.put(key, b"x")
    storage.delete(key)
    with pytest.raises(ObjectNotFoundError):
        storage.get(key)


def test_ensure_bucket_idempotent(storage: Storage) -> None:
    storage.ensure_bucket()
    names = [b["Name"] for b in boto3.client("s3").list_buckets()["Buckets"]]
    assert names == ["test-bucket"]


def test_signed_url_uses_configured_ttl(storage: Storage) -> None:
    key = object_key(1, 2, SHA)
    storage.put(key, b"x")
    url = storage.signed_url(key)
    assert key in url
    assert "X-Amz-Expires=60" in url
    assert "X-Amz-Expires=5" in storage.signed_url(key, expires_in=5)


def test_signed_url_rejects_nonpositive_ttl(storage: Storage) -> None:
    with pytest.raises(ValueError):
        storage.signed_url("k", expires_in=0)

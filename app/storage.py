"""Schmale Schnittstelle zum S3-kompatiblen Objektspeicher (MinIO)."""

import re
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import Settings, get_settings

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ID_RE = re.compile(r"[0-9]+")


class ObjectNotFoundError(Exception):
    """Objekt existiert nicht (enthält nur den Fehlercode, keinen Inhalt)."""


def _check_id(name: str, value: int) -> int:
    # bool ist eine int-Unterklasse; ausschliessen. Nur nichtnegative Ganzzahlen.
    if isinstance(value, bool) or not isinstance(value, int) or not _ID_RE.fullmatch(str(value)):
        raise ValueError(f"{name} muss eine nichtnegative Ganzzahl sein")
    return value


def object_key(buero_id: int, dossier_id: int, sha256: str) -> str:
    """Objektpfad `buero/<id>/dossier/<id>/<sha256>.pdf`."""
    buero_id = _check_id("buero_id", buero_id)
    dossier_id = _check_id("dossier_id", dossier_id)
    if not _SHA256_RE.fullmatch(sha256):
        raise ValueError("sha256 muss 64 Hex-Zeichen (klein) enthalten")
    return f"buero/{buero_id}/dossier/{dossier_id}/{sha256}.pdf"


class Storage:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._bucket = self._settings.s3_bucket
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=self._settings.s3_endpoint or None,
            aws_access_key_id=self._settings.s3_access_key,
            aws_secret_access_key=self._settings.s3_secret_key,
            region_name=self._settings.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self) -> None:
        """Legt den Bucket an, falls er fehlt (idempotent)."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchBucket", "NotFound"):
                raise
            self._client.create_bucket(Bucket=self._bucket)

    def put(
        self,
        buero_id: int,
        dossier_id: int,
        sha256: str,
        data: bytes,
        content_type: str = "application/pdf",
    ) -> str:
        """Speichert das Objekt im Präfix des Büros und gibt den Schlüssel zurück."""
        key = object_key(buero_id, dossier_id, sha256)
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return key

    def get(self, buero_id: int, dossier_id: int, sha256: str) -> bytes:
        key = object_key(buero_id, dossier_id, sha256)
        try:
            body: bytes = self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise ObjectNotFoundError(key) from None
            raise
        return body

    def delete(self, buero_id: int, dossier_id: int, sha256: str) -> None:
        key = object_key(buero_id, dossier_id, sha256)
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def signed_url(
        self, buero_id: int, dossier_id: int, sha256: str, expires_in: int | None = None
    ) -> str:
        key = object_key(buero_id, dossier_id, sha256)
        ttl = self._settings.signed_url_ttl_seconds if expires_in is None else expires_in
        if ttl <= 0:
            raise ValueError("expires_in muss positiv sein")
        url: str = self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=ttl
        )
        return url

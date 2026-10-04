"""Einmal-Tokens für Einladung und Passwort-Reset (ADR 0005).

Das Klartext-Token geht nur per Mail an den Empfänger; gespeichert wird der SHA-256-Hash.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

EINLADUNG_GUELTIG = timedelta(days=7)
RESET_GUELTIG = timedelta(hours=2)


class TokenError(Exception):
    """`code`: TOKEN_INVALID, TOKEN_EXPIRED oder TOKEN_USED."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def neues_token() -> tuple[str, str]:
    """Liefert (Klartext, Hash)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def jetzt() -> datetime:
    return datetime.now(UTC)


def pruefe(row: Any | None) -> None:
    """Prüft ein Token-Objekt (`used_at`, `expires_at`, optional `revoked_at`)."""
    if row is None or getattr(row, "revoked_at", None) is not None:
        raise TokenError("TOKEN_INVALID")
    if row.used_at is not None:
        raise TokenError("TOKEN_USED")
    if row.expires_at <= jetzt():
        raise TokenError("TOKEN_EXPIRED")

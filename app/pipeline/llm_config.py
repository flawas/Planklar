"""KI-Konfiguration: Werte aus der Datenbank (im GUI gesetzt), sonst aus den Umgebungsvariablen.

Der API-Schlüssel liegt mit Fernet verschlüsselt in der Datenbank; der Schlüssel dazu wird aus
`AUTH_SECRET` abgeleitet. Wird `AUTH_SECRET` gewechselt, muss der API-Schlüssel neu gesetzt
werden. Der Klartext verlässt dieses Modul nur Richtung LiteLLM und wird nie geloggt.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import KiEinstellung
from app.db.session import get_sessionmaker

_KEY_CONTEXT = b"liquet-ki-einstellung-v1"


@dataclass(frozen=True)
class LLMConfig:
    model: str
    api_key: str
    api_base: str


def _fernet() -> Fernet:
    secret = get_settings().auth_secret
    if not secret:
        raise RuntimeError("AUTH_SECRET ist nicht gesetzt")
    digest = hashlib.sha256(_KEY_CONTEXT + secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_key(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_key(token: str) -> str:
    """Leerer String bei leerem oder nicht mehr entschlüsselbarem Wert (z. B. neues Secret)."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""


def key_lesbar(token: str) -> bool:
    """Ob ein gespeichertes Chiffrat mit dem aktuellen `AUTH_SECRET` entschlüsselbar ist."""
    if not token:
        return False
    try:
        _fernet().decrypt(token.encode())
    except InvalidToken:
        return False
    return True


def get_row(session: Session) -> KiEinstellung | None:
    return session.get(KiEinstellung, 1)


def save_config(
    session: Session,
    *,
    model: str,
    api_base: str,
    api_key: str | None = None,
    clear_key: bool = False,
) -> KiEinstellung:
    """Speichert die Konfiguration. `api_key=None`/leer lässt den bestehenden Schlüssel stehen."""
    row = get_row(session)
    if row is None:
        row = KiEinstellung(id=1)
        session.add(row)
    row.modell = model
    row.api_base = api_base
    if clear_key:
        row.api_key_verschluesselt = ""
    elif api_key:
        row.api_key_verschluesselt = encrypt_key(api_key)
    session.commit()
    return row


def load_config(session: Session | None = None) -> LLMConfig:
    """Datenbankwerte haben Vorrang vor `LLM_MODEL`/`LLM_API_KEY`; je Feld Fallback auf Env."""
    settings = get_settings()
    if session is None:
        try:
            with get_sessionmaker()() as own:
                row = get_row(own)
        except SQLAlchemyError:  # Datenbank/Tabelle nicht erreichbar: Umgebungswerte genügen
            row = None
    else:
        row = get_row(session)
    if row is None:
        return LLMConfig(settings.llm_model, settings.llm_api_key, "")
    return LLMConfig(
        row.modell or settings.llm_model,
        decrypt_key(row.api_key_verschluesselt) or settings.llm_api_key,
        row.api_base,
    )

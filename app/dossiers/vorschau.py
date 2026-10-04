"""Seitenvorschau: gerenderte Seite als PNG, nur über kurzlebige signierte URL.

Die URL trägt Büro, Seite und Ablauf, signiert per HMAC (`auth_secret`). Der Abruf prüft
zusätzlich Anmeldung und Büro-Scope; Inhalte landen weder in Logs noch im Token.
"""

import base64
import hashlib
import hmac
import time
import uuid

from app.config import get_settings
from app.db import models as db
from app.dossiers.scope import BueroScope
from app.pipeline.preprocess import open_pdf
from app.storage import Storage

VORSCHAU_DPI = 110
PREFIX = "/vorschau/"


class TokenError(Exception):
    """Ungültiges oder abgelaufenes Vorschau-Token."""


def _mac(payload: str) -> str:
    key = get_settings().auth_secret.encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def sign(
    buero_id: uuid.UUID, seite_id: uuid.UUID, ttl: int | None = None, now: float | None = None
) -> str:
    """Token `<seite>.<büro>.<ablauf>.<mac>` (nur Bezeichner, keine Inhalte)."""
    lifetime = get_settings().signed_url_ttl_seconds if ttl is None else ttl
    if lifetime <= 0:
        raise ValueError("ttl muss positiv sein")
    ablauf = int((time.time() if now is None else now) + lifetime)
    payload = f"{seite_id}.{buero_id}.{ablauf}"
    return base64.urlsafe_b64encode(f"{payload}.{_mac(payload)}".encode()).decode().rstrip("=")


def verify(token: str, now: float | None = None) -> tuple[uuid.UUID, uuid.UUID]:
    """Liefert (büro_id, seite_id) eines gültigen Tokens, sonst `TokenError`."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        seite, buero, ablauf, mac = raw.split(".")
        if not hmac.compare_digest(mac, _mac(f"{seite}.{buero}.{ablauf}")):
            raise TokenError
        if int(ablauf) < (time.time() if now is None else now):
            raise TokenError
        return uuid.UUID(buero), uuid.UUID(seite)
    except TokenError:
        raise
    except Exception:
        raise TokenError from None


def url_fuer(buero_id: uuid.UUID, seite_id: uuid.UUID) -> str:
    return PREFIX + sign(buero_id, seite_id)


def render_seite(scope: BueroScope, storage: Storage, seite: db.Seite) -> bytes:
    """Rendert die Seite des Belegs als PNG (Büro-Scope wird über das Dokument erzwungen)."""
    dokument = scope.get_dokument(seite.dokument_id)
    data = storage.get(scope.buero_id, dokument.dossier_id, dokument.sha256)
    with open_pdf(data) as doc:
        png: bytes = doc[seite.nummer - 1].get_pixmap(dpi=VORSCHAU_DPI, alpha=False).tobytes("png")
    return png

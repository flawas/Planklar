"""Rate-Limit und temporäre Sperre für Logins, je E-Mail und je IP.

Gezählt werden Fehlversuche im gleitenden Fenster. Schlüssel sind SHA-256-Hashes, damit weder
E-Mail noch IP im Klartext gespeichert werden; unbekannte E-Mails zählen gleich wie bekannte
(keine Auskunft über Konten). Ist eine Grenze erreicht, wird auch das richtige Passwort
abgewiesen, bis der älteste Fehlversuch aus dem Fenster fällt.
"""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import LoginFehlversuch

EMAIL = "email"
IP = "ip"


def _hash(wert: str) -> str:
    return hashlib.sha256(wert.strip().lower().encode()).hexdigest()


def _grenzen() -> dict[str, int]:
    s = get_settings()
    return {EMAIL: s.login_max_fehlversuche_email, IP: s.login_max_fehlversuche_ip}


def _schluessel(email: str, ip: str | None) -> list[tuple[str, str]]:
    schluessel = [(EMAIL, _hash(email))]
    if ip:
        schluessel.append((IP, _hash(ip)))
    return schluessel


def sperre_verbleibend(session: Session, email: str, ip: str | None) -> int:
    """Sekunden bis zur Aufhebung der Sperre; 0, wenn der Login erlaubt ist."""
    fenster = get_settings().login_fenster_sekunden
    grenzen = _grenzen()
    jetzt = datetime.now(UTC)
    seit = jetzt - timedelta(seconds=fenster)
    verbleibend = 0
    for art, schluessel in _schluessel(email, ip):
        zeiten = list(
            session.execute(
                select(LoginFehlversuch.zeitpunkt)
                .where(
                    LoginFehlversuch.art == art,
                    LoginFehlversuch.schluessel == schluessel,
                    LoginFehlversuch.zeitpunkt > seit,
                )
                .order_by(LoginFehlversuch.zeitpunkt.desc())
                .limit(grenzen[art])
            ).scalars()
        )
        if len(zeiten) >= grenzen[art]:
            # Entsperrt, sobald der Fehlversuch an der Grenze das Fenster verlässt
            ablauf = zeiten[-1] + timedelta(seconds=fenster)
            verbleibend = max(verbleibend, int((ablauf - jetzt).total_seconds()) + 1)
    return verbleibend


def fehlversuch_erfassen(session: Session, email: str, ip: str | None) -> None:
    for art, schluessel in _schluessel(email, ip):
        session.add(LoginFehlversuch(art=art, schluessel=schluessel))
    # Abgelaufene Einträge aufräumen, damit die Tabelle klein bleibt
    veraltet = datetime.now(UTC) - timedelta(seconds=get_settings().login_fenster_sekunden)
    session.execute(delete(LoginFehlversuch).where(LoginFehlversuch.zeitpunkt < veraltet))
    session.commit()


def zuruecksetzen(session: Session, email: str) -> None:
    """Nach erfolgreichem Login zählt der Fehlversuchszähler der E-Mail wieder bei null."""
    session.execute(
        delete(LoginFehlversuch).where(
            LoginFehlversuch.art == EMAIL, LoginFehlversuch.schluessel == _hash(email)
        )
    )
    session.commit()

"""Persistiert den Regelkatalog als `Regelset`/`Regel`-Zeilen (ohne Duplikate)."""

from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import models as db
from app.rules.loader import DEFAULT_ROOT, load_catalog
from app.rules.models import Kanton
from app.rules.resolve import Regelset, merge


def _scopes(root: Path) -> list[Regelset]:
    """Je Kanton das Kantonsset und je Gemeinde mit eigenen Regeln das effektive Set."""
    sets: list[Regelset] = []
    for _, regeln in sorted(load_catalog(root).items()):
        sets.append(merge(regeln, None))
        sets.extend(merge(regeln, gemeinde) for gemeinde in sorted(regeln.gemeinden))
    return sets


def pruefe_katalog(root: Path = DEFAULT_ROOT) -> list[Regelset]:
    """Lädt und validiert den Katalog ohne Datenbankzugriff (wirft `RegelLadeFehler`)."""
    return _scopes(root)


def _existiert(session: Session, kanton: Kanton, gemeinde: str | None, hash_: str) -> bool:
    stmt = select(db.Regelset.id).where(
        db.Regelset.kanton == db.Kanton(kanton.value),
        db.Regelset.regelset_hash == hash_,
        (db.Regelset.gemeinde.is_(None) if gemeinde is None else db.Regelset.gemeinde == gemeinde),
    )
    return session.execute(stmt.limit(1)).first() is not None


def lade_katalog(session: Session, git_commit: str, root: Path = DEFAULT_ROOT) -> list[db.Regelset]:
    """Schreibt neue Regelset-Stände; gibt nur die neu angelegten Zeilen zurück.

    Ein bereits gespeicherter (Kanton, Gemeinde, Hash) wird nicht dupliziert, auch nicht
    bei parallelem Start mehrerer Web-Prozesse (Advisory-Lock bis zum Commit).
    Bei unverändertem Hash bleibt der bereits gespeicherte `git_commit` bewusst unverändert.
    """
    sets = _scopes(root)  # Fehler vor jeglichem DB-Zugriff
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext('planklar_regelset_laden'))"))
    neu: list[db.Regelset] = []
    for rs in sets:
        if _existiert(session, rs.kanton, rs.gemeinde, rs.hash):
            continue
        zeile = db.Regelset(
            kanton=db.Kanton(rs.kanton.value),
            gemeinde=rs.gemeinde,
            git_commit=git_commit,
            regelset_hash=rs.hash,
            regeln=[
                db.Regel(
                    regel_id=r.id,
                    titel=r.titel,
                    pruefmethode=r.check.value,
                    schwere=r.schwere.value,
                    bedingung=r.when,
                    anforderung=r.requires.model_dump(mode="json"),
                    quelle=r.quelle.model_dump(mode="json"),
                    stand=r.stand,
                )
                for r in rs.regeln
            ],
        )
        session.add(zeile)
        neu.append(zeile)
    session.commit()
    return neu

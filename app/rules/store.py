"""Persistiert den Regelkatalog: pro (Kanton, Gemeinde) ein Regelset je Hash."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Kanton as DbKanton
from app.db.models import Regel as DbRegel
from app.db.models import Regelset as DbRegelset
from app.rules.loader import DEFAULT_ROOT, load_catalog
from app.rules.resolve import Regelset, merge


def _already_stored(session: Session, regelset: Regelset) -> bool:
    stmt = select(DbRegelset.id).where(
        DbRegelset.kanton == DbKanton(regelset.kanton.value),
        DbRegelset.gemeinde.is_(None)
        if regelset.gemeinde is None
        else DbRegelset.gemeinde == regelset.gemeinde,
        DbRegelset.hash == regelset.hash,
    )
    return session.execute(stmt).first() is not None


def _store(session: Session, regelset: Regelset, git_ref: str) -> None:
    session.add(
        DbRegelset(
            kanton=DbKanton(regelset.kanton.value),
            gemeinde=regelset.gemeinde,
            git_ref=git_ref,
            hash=regelset.hash,
            regeln=[
                DbRegel(
                    regel_id=r.id,
                    titel=r.titel,
                    check=r.check.value,
                    schwere=r.schwere.value,
                    when=r.when,
                    requires=r.requires.model_dump(mode="json"),
                    quelle=r.quelle.model_dump(mode="json"),
                    stand=r.stand,
                )
                for r in regelset.regeln
            ],
        )
    )


def sync_catalog(session: Session, git_ref: str, root: Path = DEFAULT_ROOT) -> int:
    """Lädt den Katalog und legt unbekannte Regelsets an; gibt die Anzahl neuer zurück.

    Wirft `RegelLadeFehler` bei ungültigem Katalog; dann wird nichts geschrieben.
    """
    neu = 0
    for regeln in load_catalog(root).values():
        for gemeinde in (None, *sorted(regeln.gemeinden)):
            regelset = merge(regeln, gemeinde)
            if _already_stored(session, regelset):
                continue
            _store(session, regelset, git_ref)
            neu += 1
    session.commit()
    return neu

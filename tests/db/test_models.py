import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Befund,
    Buero,
    Dokument,
    Dossier,
    Dossierstatus,
    Ergebnis,
    Kanton,
    Pruefstatus,
    Pruefung,
    Seite,
    User,
    Vorhabenstyp,
)


@pytest.fixture
def session(engine: Engine):
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    with Session(engine) as s:
        yield s


def test_user_gehoert_zu_buero(session: Session) -> None:
    buero = Buero(name="Muster AG")
    session.add(User(email="a@example.org", hashed_password="x", buero=buero))
    session.commit()
    assert buero.users[0].buero_id == buero.id
    assert buero.users[0].is_active is True


def test_user_braucht_buero(session: Session) -> None:
    session.add(User(email="a@example.org", hashed_password="x"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_email_eindeutig(session: Session) -> None:
    buero = Buero(name="Muster AG")
    session.add_all(
        [
            User(email="a@example.org", hashed_password="x", buero=buero),
            User(email="a@example.org", hashed_password="y", buero=buero),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def _dossier(buero: Buero, **kw) -> Dossier:
    return Dossier(
        buero=buero,
        kanton=Kanton.LU,
        gemeinde="Luzern",
        vorhabenstyp=Vorhabenstyp.NEUBAU_EFH_MFH,
        **kw,
    )


def test_dossier_dokument_seite(session: Session) -> None:
    dossier = _dossier(Buero(name="Muster AG"), attribute={"gebaeudehoehe": 8.5})
    dok = Dokument(dateiname="a.pdf", sha256="a" * 64, seitenzahl=1, speicherpfad="p/a.pdf")
    dok.seiten.append(
        Seite(nummer=1, plantyp="Grundriss", konfidenz=0.9, merkmale={"massstab": "1:100"})
    )
    dossier.dokumente.append(dok)
    session.add(dossier)
    session.commit()
    session.expire_all()
    d = session.query(Dossier).one()
    assert d.status is Dossierstatus.ENTWURF
    assert d.attribute == {"gebaeudehoehe": 8.5}
    assert d.dokumente[0].seiten[0].merkmale == {"massstab": "1:100"}


def test_dossier_braucht_buero(session: Session) -> None:
    session.add(Dossier(kanton=Kanton.SZ, gemeinde="Schwyz", vorhabenstyp=Vorhabenstyp.UMBAU_ANBAU))
    with pytest.raises(IntegrityError):
        session.commit()


def test_kanton_nur_lu_sz(session: Session) -> None:
    session.add(_dossier(Buero(name="B")))
    session.flush()
    with pytest.raises(DBAPIError):
        session.execute(text("UPDATE dossier SET kanton = 'ZH'"))


def test_dokument_doppel_pro_dossier_verhindert(session: Session) -> None:
    dossier = _dossier(Buero(name="B"))
    for name in ("a.pdf", "b.pdf"):
        dossier.dokumente.append(
            Dokument(dateiname=name, sha256="a" * 64, seitenzahl=1, speicherpfad=name)
        )
    session.add(dossier)
    with pytest.raises(IntegrityError):
        session.commit()


def _pruefung(session: Session, **kw) -> Pruefung:
    dossier = _dossier(Buero(name="B"))
    pruefung = Pruefung(
        dossier=dossier,
        regelset_hash=kw.pop("regelset_hash", "a" * 64),
        modellversion=kw.pop("modellversion", "modell-1"),
        **kw,
    )
    session.add(pruefung)
    session.flush()
    return pruefung


def test_pruefung_speichert_hash_und_modellversion(session: Session) -> None:
    pruefung = _pruefung(session)
    session.commit()
    session.expire_all()
    p = session.query(Pruefung).one()
    assert (p.regelset_hash, p.modellversion) == ("a" * 64, "modell-1")
    assert p.status is Pruefstatus.LAEUFT
    assert p.gestartet_am is not None
    assert p.beendet_am is None
    assert p.id == pruefung.id


@pytest.mark.parametrize("feld", ["regelset_hash", "modellversion"])
def test_pruefung_braucht_hash_und_modellversion(session: Session, feld: str) -> None:
    dossier = _dossier(Buero(name="B"))
    felder = {"regelset_hash": "a" * 64, "modellversion": "m"}
    del felder[feld]
    session.add(Pruefung(dossier=dossier, **felder))
    with pytest.raises(IntegrityError):
        session.commit()


def test_befund_mit_belegen_und_override(session: Session) -> None:
    pruefung = _pruefung(session)
    seite_id = str(uuid.uuid4())
    pruefung.befunde.append(
        Befund(
            regel_id="lu.r1",
            ergebnis=Ergebnis.UNSICHER,
            belege=[seite_id],
            override_ergebnis=Ergebnis.ERFUELLT,
            override_begruendung="Planer bestätigt",
        )
    )
    session.commit()
    session.expire_all()
    b = session.query(Befund).one()
    assert b.ergebnis is Ergebnis.UNSICHER
    assert b.belege == [seite_id]
    assert b.override_ergebnis is Ergebnis.ERFUELLT


def test_befund_ohne_belege_hat_leere_liste(session: Session) -> None:
    pruefung = _pruefung(session)
    pruefung.befunde.append(Befund(regel_id="lu.r1", ergebnis=Ergebnis.MANUELL))
    session.commit()
    assert session.query(Befund).one().belege == []


def test_override_braucht_begruendung(session: Session) -> None:
    pruefung = _pruefung(session)
    pruefung.befunde.append(
        Befund(
            regel_id="lu.r1",
            ergebnis=Ergebnis.FEHLT,
            override_ergebnis=Ergebnis.ERFUELLT,
            override_begruendung=" ",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_befund_ergebnis_nur_vier_werte(session: Session) -> None:
    pruefung = _pruefung(session)
    pruefung.befunde.append(Befund(regel_id="lu.r1", ergebnis=Ergebnis.FEHLT))
    session.commit()
    with pytest.raises(DBAPIError):
        session.execute(text("UPDATE befund SET ergebnis = 'ok'"))


def test_befund_pro_regel_und_pruefung_eindeutig(session: Session) -> None:
    pruefung = _pruefung(session)
    for _ in range(2):
        pruefung.befunde.append(Befund(regel_id="lu.r1", ergebnis=Ergebnis.FEHLT))
    with pytest.raises(IntegrityError):
        session.commit()

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    Befund,
    Buero,
    Dokument,
    Dossier,
    Ergebnis,
    Kanton,
    Pruefung,
    Seite,
    Vorhabenstyp,
)
from app.dossiers.scope import BueroScope, NotFoundError, get_scope, not_found


@dataclass
class World:
    session: Session
    a: BueroScope
    b: BueroScope
    dossier_id: uuid.UUID
    dokument_id: uuid.UUID
    seite_id: uuid.UUID
    pruefung_id: uuid.UUID
    befund_id: uuid.UUID


@pytest.fixture
def world(engine: Engine) -> Iterator[World]:
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        a, b = Buero(name="A"), Buero(name="B")
        s.add_all([a, b])
        s.flush()
        scope_a = BueroScope(s, a.id)
        d = scope_a.add_dossier(
            kanton=Kanton.LU, gemeinde="Luzern", vorhabenstyp=Vorhabenstyp.UMBAU_ANBAU
        )
        dok = scope_a.add_dokument(
            d.id, dateiname="x.pdf", sha256="a" * 64, seitenzahl=1, speicherpfad="p"
        )
        seite = Seite(dokument_id=dok.id, nummer=1)
        s.add(seite)
        pruefung = scope_a.add_pruefung(d.id, regelset_hash="h" * 64, modellversion="m1")
        befund = scope_a.add_befund(pruefung.id, regel_id="lu.r1", ergebnis=Ergebnis.FEHLT)
        s.commit()
        yield World(s, scope_a, BueroScope(s, b.id), d.id, dok.id, seite.id, pruefung.id, befund.id)


Op = Callable[[BueroScope, World], Any]

FREMDZUGRIFF: dict[str, Op] = {
    "get_dossier": lambda sc, w: sc.get_dossier(w.dossier_id),
    "update_dossier": lambda sc, w: sc.update_dossier(w.dossier_id, gemeinde="Hack"),
    "delete_dossier": lambda sc, w: sc.delete_dossier(w.dossier_id),
    "list_dokumente": lambda sc, w: sc.list_dokumente(w.dossier_id),
    "add_dokument": lambda sc, w: sc.add_dokument(
        w.dossier_id, dateiname="y.pdf", sha256="b" * 64, seitenzahl=1, speicherpfad="q"
    ),
    "get_dokument": lambda sc, w: sc.get_dokument(w.dokument_id),
    "delete_dokument": lambda sc, w: sc.delete_dokument(w.dokument_id),
    "list_seiten": lambda sc, w: sc.list_seiten(w.dokument_id),
    "get_seite": lambda sc, w: sc.get_seite(w.seite_id),
    "update_seite": lambda sc, w: sc.update_seite(w.seite_id, plantyp="grundriss"),
    "get_or_add_seite": lambda sc, w: sc.get_or_add_seite(w.dokument_id, 2),
    "lock_dossier": lambda sc, w: sc.lock_dossier(w.dossier_id),
    "hat_aktiven_lauf": lambda sc, w: sc.hat_aktiven_lauf(w.dossier_id, timedelta(minutes=1)),
    "list_pruefungen": lambda sc, w: sc.list_pruefungen(w.dossier_id),
    "get_pruefung": lambda sc, w: sc.get_pruefung(w.pruefung_id),
    "add_pruefung": lambda sc, w: sc.add_pruefung(
        w.dossier_id, regelset_hash="x" * 64, modellversion="m"
    ),
    "update_pruefung": lambda sc, w: sc.update_pruefung(w.pruefung_id, seiten_fertig=5),
    "claim_pruefung": lambda sc, w: sc.claim_pruefung(w.pruefung_id, timedelta(minutes=1)),
    "release_pruefung": lambda sc, w: sc.release_pruefung(w.pruefung_id),
    "seite_fertig": lambda sc, w: sc.seite_fertig(w.pruefung_id, timedelta(minutes=1)),
    "save_befund": lambda sc, w: sc.save_befund(
        w.pruefung_id, regel_id="lu.r2", ergebnis=Ergebnis.ERFUELLT
    ),
    "prune_befunde": lambda sc, w: sc.prune_befunde(w.pruefung_id, set()),
    "list_befunde": lambda sc, w: sc.list_befunde(w.pruefung_id),
    "get_befund": lambda sc, w: sc.get_befund(w.befund_id),
    "add_befund": lambda sc, w: sc.add_befund(
        w.pruefung_id, regel_id="lu.r2", ergebnis=Ergebnis.ERFUELLT
    ),
    "set_override": lambda sc, w: sc.set_override(w.befund_id, Ergebnis.ERFUELLT, "Hack"),
}


@pytest.mark.parametrize("name", FREMDZUGRIFF)
def test_buero_b_sieht_und_aendert_nichts_von_buero_a(world: World, name: str) -> None:
    with pytest.raises(NotFoundError):
        FREMDZUGRIFF[name](world.b, world)
    world.session.rollback()
    assert world.session.query(Dossier).one().gemeinde == "Luzern"
    assert world.session.query(Dokument).count() == 1
    assert world.session.query(Seite).one().plantyp is None
    assert world.session.query(Pruefung).count() == 1
    assert world.session.get_one(Befund, world.befund_id).override_ergebnis is None


def test_eigenes_buero_hat_zugriff(world: World) -> None:
    assert world.a.get_dossier(world.dossier_id).id == world.dossier_id
    assert [d.id for d in world.a.list_dossiers()] == [world.dossier_id]
    assert world.a.get_dokument(world.dokument_id).dossier_id == world.dossier_id
    assert world.a.get_seite(world.seite_id).nummer == 1
    assert world.a.update_dossier(world.dossier_id, gemeinde="Kriens").gemeinde == "Kriens"


def test_liste_von_buero_b_ist_leer(world: World) -> None:
    assert world.b.list_dossiers() == []


def test_add_dossier_ignoriert_fremde_buero_id(world: World) -> None:
    d = world.b.add_dossier(
        buero_id=world.a.buero_id,
        kanton=Kanton.SZ,
        gemeinde="Schwyz",
        vorhabenstyp=Vorhabenstyp.UMBAU_ANBAU,
    )
    assert d.buero_id == world.b.buero_id


def test_unbekannte_id_ist_not_found(world: World) -> None:
    with pytest.raises(NotFoundError):
        world.a.get_dossier(uuid.uuid4())


def _constant(scope: BueroScope) -> Callable[[], BueroScope]:
    return lambda: scope


def test_dependency_liefert_scope_des_users_und_404(world: World) -> None:
    app = FastAPI()

    @app.get("/d/{dossier_id}")
    def read(dossier_id: uuid.UUID, scope: BueroScope = Depends(get_scope)) -> dict[str, str]:
        try:
            return {"id": str(scope.get_dossier(dossier_id).id)}
        except NotFoundError:
            raise not_found() from None

    for scope, expected in ((world.a, 200), (world.b, 404)):
        app.dependency_overrides[get_scope] = _constant(scope)
        assert TestClient(app).get(f"/d/{world.dossier_id}").status_code == expected


def test_eigenes_buero_pruefung_und_override(world: World) -> None:
    assert [p.id for p in world.a.list_pruefungen(world.dossier_id)] == [world.pruefung_id]
    assert [b.id for b in world.a.list_befunde(world.pruefung_id)] == [world.befund_id]
    befund = world.a.set_override(world.befund_id, Ergebnis.ERFUELLT, " Beleg liegt vor ")
    assert befund.override_begruendung == "Beleg liegt vor"
    assert befund.override_am is not None
    assert befund.ergebnis is Ergebnis.FEHLT


def test_override_ohne_begruendung_abgelehnt(world: World) -> None:
    with pytest.raises(ValueError):
        world.a.set_override(world.befund_id, Ergebnis.ERFUELLT, "  ")


def test_scope_setzt_buero_id_auf_allen_kindern(world: World) -> None:
    ids = {
        Dokument: world.dokument_id,
        Seite: world.seite_id,
        Pruefung: world.pruefung_id,
        Befund: world.befund_id,
    }
    for modell, id_ in ids.items():
        assert world.session.get(modell, id_).buero_id == world.a.buero_id, modell.__name__


def test_neues_dokument_und_neue_pruefung_gehoeren_zum_scope_buero(world: World) -> None:
    dok = world.a.add_dokument(
        world.dossier_id, dateiname="y.pdf", sha256="b" * 64, seitenzahl=1, speicherpfad="q"
    )
    seite = world.a.get_or_add_seite(dok.id, 1)
    pruefung = world.a.add_pruefung(world.dossier_id, regelset_hash="h" * 64, modellversion="m2")
    befund = world.a.add_befund(pruefung.id, regel_id="lu.r2", ergebnis=Ergebnis.FEHLT)
    assert {dok.buero_id, seite.buero_id, pruefung.buero_id, befund.buero_id} == {world.a.buero_id}


def test_buero_id_wird_bei_relationship_anlage_vom_elternobjekt_uebernommen(
    world: World,
) -> None:
    pruefung = world.session.get(Pruefung, world.pruefung_id)
    pruefung.befunde.append(Befund(regel_id="lu.r3", ergebnis=Ergebnis.MANUELL))
    world.session.flush()
    assert pruefung.befunde[-1].buero_id == world.a.buero_id

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Buero, Dokument, Dossier, Kanton, Seite, Vorhabenstyp
from app.dossiers.scope import BueroScope, NotFoundError, get_scope, not_found


@dataclass
class World:
    session: Session
    a: BueroScope
    b: BueroScope
    dossier_id: uuid.UUID
    dokument_id: uuid.UUID
    seite_id: uuid.UUID


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
        s.commit()
        yield World(s, scope_a, BueroScope(s, b.id), d.id, dok.id, seite.id)


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
}


@pytest.mark.parametrize("name", FREMDZUGRIFF)
def test_buero_b_sieht_und_aendert_nichts_von_buero_a(world: World, name: str) -> None:
    with pytest.raises(NotFoundError):
        FREMDZUGRIFF[name](world.b, world)
    world.session.rollback()
    assert world.session.query(Dossier).one().gemeinde == "Luzern"
    assert world.session.query(Dokument).count() == 1
    assert world.session.query(Seite).one().plantyp is None


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

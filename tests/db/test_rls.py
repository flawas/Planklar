import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.db.models import Ergebnis, Kanton, Vorhabenstyp
from app.dossiers.scope import BueroScope

TABELLEN = ["dossier", "dokument", "seite", "pruefung", "befund"]


@pytest.fixture
def rls_db(engine: Engine) -> Iterator[Engine]:
    """Migriertes Schema; Zugriffe laufen als `liquet_app` (ohne BYPASSRLS)."""
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        if not conn.scalar(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ):
            pytest.skip("Test-DB-Benutzer ist weder Superuser noch BYPASSRLS; Rollenwechsel unklar")
    yield engine


@contextmanager
def _app_session(engine: Engine) -> Iterator[Session]:
    """Session als `liquet_app`; die Rolle wird vor der Rückgabe an den Pool zurückgesetzt."""
    with Session(engine) as session:
        session.execute(text("SET ROLE liquet_app"))
        try:
            yield session
        finally:
            session.rollback()
            session.execute(text("RESET ROLE"))
            session.commit()


def _seed(engine: Engine) -> tuple[uuid.UUID, uuid.UUID]:
    from app.db.models import Buero

    with Session(engine) as s:
        a, b = Buero(name="A"), Buero(name="B")
        s.add_all([a, b])
        s.commit()
        ids = (a.id, b.id)
    for buero_id in ids:
        with _app_session(engine) as s:
            scope = BueroScope(s, buero_id)
            d = scope.add_dossier(
                kanton=Kanton.LU, gemeinde="Luzern", vorhabenstyp=Vorhabenstyp.UMBAU_ANBAU
            )
            dok = scope.add_dokument(
                d.id, dateiname="x.pdf", sha256="a" * 64, seitenzahl=1, speicherpfad="p"
            )
            scope.get_or_add_seite(dok.id, 1)
            p = scope.add_pruefung(d.id, regelset_hash="h" * 64, modellversion="m")
            scope.add_befund(p.id, regel_id="lu.r1", ergebnis=Ergebnis.FEHLT)
            s.commit()
    return ids


def test_app_rolle_hat_kein_bypassrls(rls_db: Engine) -> None:
    with rls_db.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'liquet_app'")
        ).one()
    assert tuple(row) == (False, False)


@pytest.mark.parametrize("tabelle", TABELLEN)
def test_roher_query_ohne_scope_liefert_nichts(rls_db: Engine, tabelle: str) -> None:
    _seed(rls_db)
    with _app_session(rls_db) as s:
        assert s.execute(text(f"SELECT count(*) FROM {tabelle}")).scalar() == 0


@pytest.mark.parametrize("tabelle", TABELLEN)
def test_roher_query_sieht_nur_eigenes_buero(rls_db: Engine, tabelle: str) -> None:
    a, b = _seed(rls_db)
    with _app_session(rls_db) as s:
        BueroScope(s, a)
        rows = s.execute(text(f"SELECT DISTINCT buero_id FROM {tabelle}")).scalars().all()
    assert rows == [a]
    assert b not in rows


def test_kontext_ueberlebt_commit(rls_db: Engine) -> None:
    a, _ = _seed(rls_db)
    with _app_session(rls_db) as s:
        BueroScope(s, a)
        s.commit()
        assert s.execute(text("SELECT count(*) FROM dossier")).scalar() == 1


def test_kontextwechsel_in_einer_session(rls_db: Engine) -> None:
    a, b = _seed(rls_db)
    with _app_session(rls_db) as s:
        for buero_id in (a, b):
            BueroScope(s, buero_id)
            assert s.execute(text("SELECT buero_id FROM dossier")).scalars().all() == [buero_id]
            s.commit()


def test_fremdes_buero_kann_nicht_geschrieben_werden(rls_db: Engine) -> None:
    a, b = _seed(rls_db)
    with _app_session(rls_db) as s:
        BueroScope(s, a)
        res = s.execute(text("UPDATE dossier SET gemeinde = 'X' WHERE buero_id = :b"), {"b": b})
        assert res.rowcount == 0
        with pytest.raises(Exception, match="row-level security"):
            s.execute(
                text(
                    "INSERT INTO dossier (id, buero_id, kanton, gemeinde, vorhabenstyp) "
                    "VALUES (gen_random_uuid(), :b, 'LU', 'X', 'umbau_anbau')"
                ),
                {"b": b},
            )


def test_retention_setzt_kontext_pro_buero(rls_db: Engine) -> None:
    from datetime import UTC, datetime, timedelta

    from app.dossiers.retention import loesche_abgelaufene_dossiers

    _seed(rls_db)

    class _Storage:
        def delete(self, *_: object) -> None:
            return None

    with _app_session(rls_db) as s:
        report = loesche_abgelaufene_dossiers(
            s,
            _Storage(),  # type: ignore[arg-type]
            30,
            now=lambda: datetime.now(UTC) + timedelta(days=60),
        )
        assert len(report.geloescht) == 2
        assert not report.fehlgeschlagen

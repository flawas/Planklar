from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

TABELLEN = {
    "buero",
    "user",
    "dossier",
    "dokument",
    "seite",
    "regelset",
    "regel",
    "pruefung",
    "befund",
    "ki_einstellung",
}


def test_upgrade_und_downgrade(engine: Engine) -> None:
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        assert TABELLEN <= set(inspect(conn).get_table_names())
        command.downgrade(cfg, "base")
        assert not TABELLEN & set(inspect(conn).get_table_names())


def test_buero_id_backfill_und_not_null(engine: Engine) -> None:
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0009")
        conn.execute(text("INSERT INTO buero (id, name) VALUES (gen_random_uuid(), 'A')"))
        conn.execute(
            text(
                "INSERT INTO dossier (id, buero_id, kanton, gemeinde, vorhabenstyp) "
                "SELECT gen_random_uuid(), id, 'LU', 'Luzern', 'umbau_anbau' FROM buero"
            )
        )
        conn.execute(
            text(
                "INSERT INTO dokument (id, dossier_id, dateiname, sha256, seitenzahl, speicherpfad)"
                " SELECT gen_random_uuid(), id, 'a.pdf', 'a', 1, 'p' FROM dossier"
            )
        )
        conn.execute(
            text(
                "INSERT INTO seite (id, dokument_id, nummer) "
                "SELECT gen_random_uuid(), id, 1 FROM dokument"
            )
        )
        conn.execute(
            text(
                "INSERT INTO pruefung (id, dossier_id, regelset_hash, modellversion) "
                "SELECT gen_random_uuid(), id, 'h', 'm' FROM dossier"
            )
        )
        conn.execute(
            text(
                "INSERT INTO befund (id, pruefung_id, regel_id, ergebnis) "
                "SELECT gen_random_uuid(), id, 'r', 'fehlt' FROM pruefung"
            )
        )
        command.upgrade(cfg, "0010")
        for tabelle in ("dokument", "seite", "pruefung", "befund"):
            spalte = next(c for c in inspect(conn).get_columns(tabelle) if c["name"] == "buero_id")
            assert not spalte["nullable"], tabelle
            assert any(
                i["column_names"] == ["buero_id"] for i in inspect(conn).get_indexes(tabelle)
            ), tabelle
            fremd = conn.scalar(
                text(f"SELECT count(*) FROM {tabelle} WHERE buero_id <> (SELECT id FROM buero)")
            )
            assert fremd == 0
            assert conn.scalar(text(f"SELECT count(*) FROM {tabelle}")) == 1
        command.downgrade(cfg, "0009")

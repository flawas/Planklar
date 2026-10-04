from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

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

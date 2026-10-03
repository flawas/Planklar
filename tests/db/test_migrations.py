from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect


def test_upgrade_und_downgrade(engine: Engine) -> None:
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        assert {"buero", "user"} <= set(inspect(conn).get_table_names())
        command.downgrade(cfg, "base")
        assert not {"buero", "user"} & set(inspect(conn).get_table_names())

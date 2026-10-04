"""Row-Level Security auf allen mandantengebundenen Tabellen

Policy `buero_id = app.buero_id` (ADR 0005), gesetzt von `BueroScope` per `SET LOCAL`.
Ohne Kontext ist die Policy NULL und es sind keine Zeilen sichtbar. `FORCE` bindet auch den
Tabellenbesitzer; ausgenommen bleiben Superuser und Rollen mit `BYPASSRLS`. `user` und `buero`
bleiben ohne RLS, weil der Login den Benutzer vor dem Büro-Kontext nachschlägt.

Die Rolle `liquet_app` (NOBYPASSRLS, NOLOGIN) ist die vorgesehene App-Rolle. Der Betrieb gibt
ihr per `ALTER ROLE liquet_app LOGIN PASSWORD ...` ein Login und nutzt sie in `DATABASE_URL`;
Migrationen laufen weiter mit der Besitzerrolle.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_TABELLEN = ["dossier", "dokument", "seite", "pruefung", "befund"]
_POLICY = "buero_isolation"
_BEDINGUNG = "buero_id = NULLIF(current_setting('app.buero_id', true), '')::uuid"


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'liquet_app') THEN "
        "CREATE ROLE liquet_app NOLOGIN NOSUPERUSER NOBYPASSRLS; "
        "END IF; END $$"
    )
    op.execute("GRANT USAGE ON SCHEMA public TO liquet_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO liquet_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO liquet_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO liquet_app"
    )
    for tabelle in _TABELLEN:
        op.execute(f"ALTER TABLE {tabelle} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tabelle} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {_POLICY} ON {tabelle} USING ({_BEDINGUNG}) WITH CHECK ({_BEDINGUNG})"
        )


def downgrade() -> None:
    for tabelle in reversed(_TABELLEN):
        op.execute(f"DROP POLICY {_POLICY} ON {tabelle}")
        op.execute(f"ALTER TABLE {tabelle} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tabelle} DISABLE ROW LEVEL SECURITY")
    # Die Rolle bleibt bestehen (kann Besitzerin von Rechten in anderen Datenbanken sein).

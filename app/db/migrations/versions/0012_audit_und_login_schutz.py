"""Audit-Log, Login-Fehlversuche und Session-Version

`audit_ereignis` und `login_fehlversuch` sind nicht mandantengebunden (Login-Ereignisse haben
vor der Anmeldung keinen Büro-Kontext) und enthalten nur IDs bzw. Hashes. `user.session_version`
steckt im Session-Token; eine Erhöhung macht bestehende Sitzungen ungültig.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_table(
        "audit_ereignis",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("buero_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("aktion", sa.String(100), nullable=False),
        sa.Column("objekt_typ", sa.String(50), nullable=True),
        sa.Column("objekt_id", sa.Uuid(), nullable=True),
        sa.Column(
            "zeitpunkt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_ereignis_buero_id", "audit_ereignis", ["buero_id"])
    op.create_index("ix_audit_ereignis_zeitpunkt", "audit_ereignis", ["zeitpunkt"])
    op.create_table(
        "login_fehlversuch",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("art", sa.String(10), nullable=False),
        sa.Column("schluessel", sa.String(64), nullable=False),
        sa.Column(
            "zeitpunkt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_login_fehlversuch_art_schluessel",
        "login_fehlversuch",
        ["art", "schluessel", "zeitpunkt"],
    )
    # Rechte für die RLS-App-Rolle (0011); Default-Privileges gelten nur für spätere Tabellen
    # der Migrationsrolle, daher ausdrücklich.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'liquet_app') THEN "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON audit_ereignis, login_fehlversuch "
        "TO liquet_app; END IF; END $$"
    )


def downgrade() -> None:
    op.drop_table("login_fehlversuch")
    op.drop_table("audit_ereignis")
    op.drop_column("user", "session_version")

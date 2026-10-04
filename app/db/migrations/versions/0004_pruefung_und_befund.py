"""Prüflauf und Befund

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

ERGEBNISSE = ("erfüllt", "fehlt", "unsicher", "manuell")


def _ergebnis(name: str) -> sa.Enum:
    return sa.Enum(*ERGEBNISSE, name=name, native_enum=False, create_constraint=True, length=50)


def upgrade() -> None:
    op.create_table(
        "pruefung",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dossier_id", sa.Uuid(), nullable=False),
        sa.Column("regelset_hash", sa.String(length=64), nullable=False),
        sa.Column("modellversion", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "laeuft",
                "abgeschlossen",
                "fehlgeschlagen",
                name="pruefstatus",
                native_enum=False,
                create_constraint=True,
                length=50,
            ),
            server_default="laeuft",
            nullable=False,
        ),
        sa.Column(
            "gestartet_am", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("beendet_am", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["dossier_id"], ["dossier.id"], name=op.f("fk_pruefung_dossier_id_dossier")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pruefung")),
    )
    op.create_index(op.f("ix_pruefung_dossier_id"), "pruefung", ["dossier_id"], unique=False)
    op.create_table(
        "befund",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pruefung_id", sa.Uuid(), nullable=False),
        sa.Column("regel_id", sa.String(length=200), nullable=False),
        sa.Column("ergebnis", _ergebnis("ergebnis"), nullable=False),
        sa.Column(
            "belege",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("override_ergebnis", _ergebnis("override_ergebnis"), nullable=True),
        sa.Column("override_begruendung", sa.String(length=2000), nullable=True),
        sa.Column("override_am", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "override_ergebnis IS NULL OR length(btrim(coalesce(override_begruendung, ''))) > 0",
            name=op.f("ck_befund_override_braucht_begruendung"),
        ),
        sa.ForeignKeyConstraint(
            ["pruefung_id"], ["pruefung.id"], name=op.f("fk_befund_pruefung_id_pruefung")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_befund")),
        sa.UniqueConstraint("pruefung_id", "regel_id", name=op.f("uq_befund_pruefung_id")),
    )
    op.create_index(op.f("ix_befund_pruefung_id"), "befund", ["pruefung_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_befund_pruefung_id"), table_name="befund")
    op.drop_table("befund")
    op.drop_index(op.f("ix_pruefung_dossier_id"), table_name="pruefung")
    op.drop_table("pruefung")

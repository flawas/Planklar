"""buero_id auf dokument, seite, pruefung, befund denormalisieren

Voraussetzung für Row-Level Security (ADR 0005). Backfill über die Eltern-Kette
(dossier -> dokument -> seite, dossier -> pruefung -> befund), danach NOT NULL, FK und Index.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# (Tabelle, Eltern-Tabelle, Spalte mit Verweis auf den Eltern-Datensatz) in Abhängigkeitsreihenfolge
_TABELLEN = [
    ("dokument", "dossier", "dossier_id"),
    ("seite", "dokument", "dokument_id"),
    ("pruefung", "dossier", "dossier_id"),
    ("befund", "pruefung", "pruefung_id"),
]


def upgrade() -> None:
    for tabelle, eltern, fk in _TABELLEN:
        op.add_column(tabelle, sa.Column("buero_id", sa.Uuid(), nullable=True))
        op.execute(
            f"UPDATE {tabelle} t SET buero_id = p.buero_id FROM {eltern} p WHERE t.{fk} = p.id"
        )
        op.alter_column(tabelle, "buero_id", nullable=False)
        op.create_foreign_key(
            op.f(f"fk_{tabelle}_buero_id_buero"), tabelle, "buero", ["buero_id"], ["id"]
        )
        op.create_index(op.f(f"ix_{tabelle}_buero_id"), tabelle, ["buero_id"], unique=False)


def downgrade() -> None:
    for tabelle, _, _ in reversed(_TABELLEN):
        op.drop_index(op.f(f"ix_{tabelle}_buero_id"), table_name=tabelle)
        op.drop_constraint(op.f(f"fk_{tabelle}_buero_id_buero"), tabelle, type_="foreignkey")
        op.drop_column(tabelle, "buero_id")

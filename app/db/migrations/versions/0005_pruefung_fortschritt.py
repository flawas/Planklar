"""Fortschritt des Prüflaufs (Seiten gesamt/fertig)

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pruefung", sa.Column("seiten_gesamt", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "pruefung", sa.Column("seiten_fertig", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("pruefung", "seiten_fertig")
    op.drop_column("pruefung", "seiten_gesamt")

"""Lease am Prüflauf gegen parallele Ausführung

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pruefung", sa.Column("lauf_bis", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("pruefung", "lauf_bis")

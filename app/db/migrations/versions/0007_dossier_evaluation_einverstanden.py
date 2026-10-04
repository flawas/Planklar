"""Evaluations-Einverständnis am Dossier (Ausnahme vom Retention-Job)

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dossier",
        sa.Column(
            "evaluation_einverstanden", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("dossier", "evaluation_einverstanden")

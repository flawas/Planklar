"""KI-Anbieter-Konfiguration der Installation

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ki_einstellung",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("modell", sa.String(200), nullable=False, server_default=""),
        sa.Column("api_base", sa.String(500), nullable=False, server_default=""),
        sa.Column("api_key_verschluesselt", sa.String(2000), nullable=False, server_default=""),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="ki_einstellung_singleton"),
    )


def downgrade() -> None:
    op.drop_table("ki_einstellung")

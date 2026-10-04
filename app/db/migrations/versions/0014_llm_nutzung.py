"""LLM-Nutzung (Token und Kosten) pro Büro für die Abrechnung

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_POLICY = "buero_isolation"
_BEDINGUNG = "buero_id = NULLIF(current_setting('app.buero_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "llm_nutzung",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("buero_id", sa.Uuid(), sa.ForeignKey("buero.id"), nullable=False),
        sa.Column("pruefung_id", sa.Uuid(), nullable=True),
        sa.Column("zweck", sa.String(50), nullable=False),
        sa.Column("modell", sa.String(200), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kosten_usd", sa.Numeric(14, 8), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_llm_nutzung_buero_id", "llm_nutzung", ["buero_id"])
    op.create_index("ix_llm_nutzung_buero_zeit", "llm_nutzung", ["buero_id", "created_at"])
    op.execute("ALTER TABLE llm_nutzung ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE llm_nutzung FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_POLICY} ON llm_nutzung USING ({_BEDINGUNG}) WITH CHECK ({_BEDINGUNG})"
    )


def downgrade() -> None:
    op.drop_table("llm_nutzung")

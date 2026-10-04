"""Regelset und Regel

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regelset",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "kanton",
            sa.Enum(
                "LU", "SZ", name="kanton", native_enum=False, create_constraint=True, length=50
            ),
            nullable=False,
        ),
        sa.Column("gemeinde", sa.String(length=200), nullable=True),
        sa.Column("git_commit", sa.String(length=100), nullable=False),
        sa.Column("regelset_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "geladen_am", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regelset")),
    )
    op.create_index(
        "uq_regelset_scope_hash",
        "regelset",
        ["kanton", sa.text("coalesce(gemeinde, '')"), "regelset_hash"],
        unique=True,
    )
    op.create_table(
        "regel",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("regelset_id", sa.Uuid(), nullable=False),
        sa.Column("regel_id", sa.String(length=200), nullable=False),
        sa.Column("titel", sa.String(length=500), nullable=False),
        sa.Column("pruefmethode", sa.String(length=50), nullable=False),
        sa.Column("schwere", sa.String(length=50), nullable=False),
        sa.Column("bedingung", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("anforderung", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quelle", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stand", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["regelset_id"], ["regelset.id"], name=op.f("fk_regel_regelset_id_regelset")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regel")),
        sa.UniqueConstraint("regelset_id", "regel_id", name=op.f("uq_regel_regelset_id")),
    )
    op.create_index(op.f("ix_regel_regelset_id"), "regel", ["regelset_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_regel_regelset_id"), table_name="regel")
    op.drop_table("regel")
    op.drop_index("uq_regelset_scope_hash", table_name="regelset")
    op.drop_table("regelset")

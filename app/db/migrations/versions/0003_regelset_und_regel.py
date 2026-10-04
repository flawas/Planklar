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
        sa.Column("git_ref", sa.String(length=200), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column(
            "geladen_am", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regelset")),
        sa.UniqueConstraint("kanton", "gemeinde", "hash", name=op.f("uq_regelset_kanton")),
    )
    op.create_index(op.f("ix_regelset_hash"), "regelset", ["hash"])
    op.create_table(
        "regel",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("regelset_id", sa.Uuid(), nullable=False),
        sa.Column("regel_id", sa.String(length=200), nullable=False),
        sa.Column("titel", sa.Text(), nullable=False),
        sa.Column("check", sa.String(length=50), nullable=False),
        sa.Column("schwere", sa.String(length=50), nullable=False),
        sa.Column("when", postgresql.JSONB(), nullable=False),
        sa.Column("requires", postgresql.JSONB(), nullable=False),
        sa.Column("quelle", postgresql.JSONB(), nullable=False),
        sa.Column("stand", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["regelset_id"], ["regelset.id"], name=op.f("fk_regel_regelset_id_regelset")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regel")),
        sa.UniqueConstraint("regelset_id", "regel_id", name=op.f("uq_regel_regelset_id")),
    )
    op.create_index(op.f("ix_regel_regelset_id"), "regel", ["regelset_id"])


def downgrade() -> None:
    op.drop_table("regel")
    op.drop_table("regelset")

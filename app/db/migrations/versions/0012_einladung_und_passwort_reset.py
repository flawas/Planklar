"""Einladung und Passwort-Reset (Token nur gehasht)

Beide Tabellen bleiben ohne RLS: Das Einlösen ist öffentlich und schlägt das Token nach,
bevor ein Büro-Kontext existiert (wie `user` und `buero`).

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
    op.create_table(
        "einladung",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("buero_id", sa.Uuid(), sa.ForeignKey("buero.id"), nullable=False, index=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("rolle", sa.String(50), nullable=False, server_default="mitarbeiter"),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            sa.column("rolle").in_(["mitarbeiter", "buero_admin"]), name=op.f("ck_einladung_rolle")
        ),
    )
    op.create_table(
        "passwort_reset",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("passwort_reset")
    op.drop_table("einladung")

"""Rollenmodell: user.rolle, user.is_plattform_admin, buero.aktiv

Mapping (ADR 0005): bisherige `is_superuser=true` wurden Büro-Admins (`rolle='buero_admin'`).
`is_plattform_admin` erhalten nur explizit benannte Konten: E-Mail-Adressen (kommagetrennt)
in der Umgebungsvariable `PLATTFORM_ADMINS` beim Migrationslauf. Die Spalte `is_superuser`
bleibt bestehen, wird aber nicht mehr gelesen; das fastapi-users-Attribut zeigt auf
`is_plattform_admin`.

Revision ID: 0009
Revises: 0008
"""

import os

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "buero", sa.Column("aktiv", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "user",
        sa.Column("rolle", sa.String(50), nullable=False, server_default="mitarbeiter"),
    )
    op.create_check_constraint(
        op.f("ck_user_rolle"), "user", sa.column("rolle").in_(["mitarbeiter", "buero_admin"])
    )
    op.add_column(
        "user",
        sa.Column("is_plattform_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE \"user\" SET rolle = 'buero_admin' WHERE is_superuser")
    emails = [e.strip().lower() for e in os.environ.get("PLATTFORM_ADMINS", "").split(",")]
    for email in filter(None, emails):
        op.get_bind().execute(
            sa.text('UPDATE "user" SET is_plattform_admin = true WHERE lower(email) = :e'),
            {"e": email},
        )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_user_rolle"), "user", type_="check")
    op.drop_column("user", "is_plattform_admin")
    op.drop_column("user", "rolle")
    op.drop_column("buero", "aktiv")

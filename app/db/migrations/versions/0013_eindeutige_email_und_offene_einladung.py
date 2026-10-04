"""Eindeutigkeit: Benutzer-E-Mail ohne Gross-/Kleinschreibung, eine offene Einladung je Adresse

Revision ID: 0013
Revises: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Doppelt offene Einladungen bereinigen: nur die neueste je (Büro, Adresse) bleibt offen.
    op.execute(
        """
        UPDATE einladung SET revoked_at = now()
        WHERE used_at IS NULL AND revoked_at IS NULL AND id NOT IN (
            SELECT DISTINCT ON (buero_id, lower(email)) id FROM einladung
            WHERE used_at IS NULL AND revoked_at IS NULL
            ORDER BY buero_id, lower(email), created_at DESC
        )
        """
    )
    op.execute('CREATE UNIQUE INDEX uq_user_email_lower ON "user" (lower(email))')
    op.execute(
        "CREATE UNIQUE INDEX uq_einladung_offen ON einladung (buero_id, lower(email)) "
        "WHERE used_at IS NULL AND revoked_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX uq_einladung_offen")
    op.execute("DROP INDEX uq_user_email_lower")

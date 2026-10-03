"""Dossier, Dokument und Seite

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dossier",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("buero_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kanton",
            sa.Enum(
                "LU", "SZ", name="kanton", native_enum=False, create_constraint=True, length=50
            ),
            nullable=False,
        ),
        sa.Column("gemeinde", sa.String(length=200), nullable=False),
        sa.Column(
            "vorhabenstyp",
            sa.Enum(
                "neubau_efh_mfh",
                "umbau_anbau",
                "heizungsersatz_waermepumpe",
                name="vorhabenstyp",
                native_enum=False,
                create_constraint=True,
                length=50,
            ),
            nullable=False,
        ),
        sa.Column(
            "attribute",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "entwurf",
                "in_pruefung",
                "geprueft",
                name="dossierstatus",
                native_enum=False,
                create_constraint=True,
                length=50,
            ),
            server_default="entwurf",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["buero_id"], ["buero.id"], name=op.f("fk_dossier_buero_id_buero")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dossier")),
    )
    op.create_index(op.f("ix_dossier_buero_id"), "dossier", ["buero_id"], unique=False)
    op.create_table(
        "dokument",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dossier_id", sa.Uuid(), nullable=False),
        sa.Column("dateiname", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("seitenzahl", sa.Integer(), nullable=False),
        sa.Column("speicherpfad", sa.String(length=1000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id"], ["dossier.id"], name=op.f("fk_dokument_dossier_id_dossier")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dokument")),
        sa.UniqueConstraint("dossier_id", "sha256", name=op.f("uq_dokument_dossier_id")),
    )
    op.create_index(op.f("ix_dokument_dossier_id"), "dokument", ["dossier_id"], unique=False)
    op.create_table(
        "seite",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dokument_id", sa.Uuid(), nullable=False),
        sa.Column("nummer", sa.Integer(), nullable=False),
        sa.Column("plantyp", sa.String(length=100), nullable=True),
        sa.Column("konfidenz", sa.Float(), nullable=True),
        sa.Column(
            "merkmale", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["dokument_id"], ["dokument.id"], name=op.f("fk_seite_dokument_id_dokument")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_seite")),
        sa.UniqueConstraint("dokument_id", "nummer", name=op.f("uq_seite_dokument_id")),
    )
    op.create_index(op.f("ix_seite_dokument_id"), "seite", ["dokument_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_seite_dokument_id"), table_name="seite")
    op.drop_table("seite")
    op.drop_index(op.f("ix_dokument_dossier_id"), table_name="dokument")
    op.drop_table("dokument")
    op.drop_index(op.f("ix_dossier_buero_id"), table_name="dossier")
    op.drop_table("dossier")

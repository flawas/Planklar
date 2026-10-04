import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Kanton(enum.StrEnum):
    LU = "LU"
    SZ = "SZ"


class Vorhabenstyp(enum.StrEnum):
    NEUBAU_EFH_MFH = "neubau_efh_mfh"
    UMBAU_ANBAU = "umbau_anbau"
    HEIZUNGSERSATZ_WAERMEPUMPE = "heizungsersatz_waermepumpe"


class Dossierstatus(enum.StrEnum):
    ENTWURF = "entwurf"
    IN_PRUEFUNG = "in_pruefung"
    GEPRUEFT = "geprueft"


def _enum(cls: type[enum.StrEnum], name: str) -> Enum:
    """VARCHAR mit CHECK-Constraint statt nativem PG-Enum (einfachere Migrationen)."""
    return Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=50,
        values_callable=lambda e: [m.value for m in e],
    )


class Buero(Base):
    """Mandant: Alle Daten gehören genau einem Büro."""

    __tablename__ = "buero"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="buero")


class User(Base):
    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    buero_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buero.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(1024))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    buero: Mapped[Buero] = relationship(back_populates="users")


class Dossier(Base):
    __tablename__ = "dossier"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    buero_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buero.id"), index=True)
    kanton: Mapped[Kanton] = mapped_column(_enum(Kanton, "kanton"))
    gemeinde: Mapped[str] = mapped_column(String(200))
    vorhabenstyp: Mapped[Vorhabenstyp] = mapped_column(_enum(Vorhabenstyp, "vorhabenstyp"))
    attribute: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[Dossierstatus] = mapped_column(
        _enum(Dossierstatus, "dossierstatus"),
        default=Dossierstatus.ENTWURF,
        server_default=Dossierstatus.ENTWURF.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    buero: Mapped[Buero] = relationship()
    dokumente: Mapped[list["Dokument"]] = relationship(
        back_populates="dossier", cascade="all, delete-orphan"
    )


class Dokument(Base):
    __tablename__ = "dokument"
    __table_args__ = (UniqueConstraint("dossier_id", "sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), index=True)
    dateiname: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    seitenzahl: Mapped[int] = mapped_column(Integer)
    speicherpfad: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dossier: Mapped[Dossier] = relationship(back_populates="dokumente")
    seiten: Mapped[list["Seite"]] = relationship(
        back_populates="dokument", cascade="all, delete-orphan", order_by="Seite.nummer"
    )


class Seite(Base):
    __tablename__ = "seite"
    __table_args__ = (UniqueConstraint("dokument_id", "nummer"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dokument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dokument.id"), index=True)
    nummer: Mapped[int] = mapped_column(Integer)
    plantyp: Mapped[str | None] = mapped_column(String(100))
    konfidenz: Mapped[float | None] = mapped_column(Float)
    merkmale: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    dokument: Mapped[Dokument] = relationship(back_populates="seiten")


class Regelset(Base):
    """Geladener Stand des effektiven Regelsets für (Kanton, Gemeinde); global, nicht pro Büro."""

    __tablename__ = "regelset"
    __table_args__ = (UniqueConstraint("kanton", "gemeinde", "hash"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kanton: Mapped[Kanton] = mapped_column(_enum(Kanton, "kanton"))
    gemeinde: Mapped[str | None] = mapped_column(String(200))
    git_ref: Mapped[str] = mapped_column(String(200))
    hash: Mapped[str] = mapped_column(String(64), index=True)
    geladen_am: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    regeln: Mapped[list["Regel"]] = relationship(
        back_populates="regelset", cascade="all, delete-orphan", order_by="Regel.regel_id"
    )


class Regel(Base):
    __tablename__ = "regel"
    __table_args__ = (UniqueConstraint("regelset_id", "regel_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    regelset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("regelset.id"), index=True)
    regel_id: Mapped[str] = mapped_column(String(200))
    titel: Mapped[str] = mapped_column(Text)
    check: Mapped[str] = mapped_column(String(50))
    schwere: Mapped[str] = mapped_column(String(50))
    when: Mapped[Any] = mapped_column(JSONB)
    requires: Mapped[dict[str, Any]] = mapped_column(JSONB)
    quelle: Mapped[dict[str, Any]] = mapped_column(JSONB)
    stand: Mapped[date] = mapped_column(Date)

    regelset: Mapped[Regelset] = relationship(back_populates="regeln")

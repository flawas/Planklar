import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    false,
    func,
    select,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.db.base import Base


class Kanton(enum.StrEnum):
    LU = "LU"
    SZ = "SZ"


class Rolle(enum.StrEnum):
    MITARBEITER = "mitarbeiter"
    BUERO_ADMIN = "buero_admin"


class Vorhabenstyp(enum.StrEnum):
    NEUBAU_EFH_MFH = "neubau_efh_mfh"
    UMBAU_ANBAU = "umbau_anbau"
    HEIZUNGSERSATZ_WAERMEPUMPE = "heizungsersatz_waermepumpe"


class Dossierstatus(enum.StrEnum):
    ENTWURF = "entwurf"
    IN_PRUEFUNG = "in_pruefung"
    GEPRUEFT = "geprueft"


class Pruefstatus(enum.StrEnum):
    LAEUFT = "laeuft"
    ABGESCHLOSSEN = "abgeschlossen"
    FEHLGESCHLAGEN = "fehlgeschlagen"


class Ergebnis(enum.StrEnum):
    ERFUELLT = "erfüllt"
    FEHLT = "fehlt"
    UNSICHER = "unsicher"
    MANUELL = "manuell"


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
    # Gesperrte Büros (aktiv=false): Login und bestehende Sitzungen werden abgewiesen
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="buero")


class User(Base):
    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    buero_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buero.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(1024))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    rolle: Mapped[Rolle] = mapped_column(
        _enum(Rolle, "rolle"), default=Rolle.MITARBEITER, server_default=Rolle.MITARBEITER.value
    )
    is_plattform_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Legacy-Spalte; fastapi-users kennt nur `is_superuser`, das Attribut zeigt auf
    # `is_plattform_admin` (ADR 0005). Die Spalte selbst wird nicht mehr gelesen.
    _is_superuser_legacy: Mapped[bool] = mapped_column(
        "is_superuser", Boolean, default=False, server_default=false()
    )
    is_superuser = synonym("is_plattform_admin")
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Steckt im Session-Token; jede Erhöhung macht bestehende Sitzungen ungültig
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
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
    # Ausdrückliches Einverständnis zur Nutzung im Evaluations-Set: nimmt vom Retention-Job aus
    evaluation_einverstanden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
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
    buero_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buero.id"), index=True)
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
    buero_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buero.id"), index=True)
    dokument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dokument.id"), index=True)
    nummer: Mapped[int] = mapped_column(Integer)
    plantyp: Mapped[str | None] = mapped_column(String(100))
    konfidenz: Mapped[float | None] = mapped_column(Float)
    merkmale: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    dokument: Mapped[Dokument] = relationship(back_populates="seiten")


class Regelset(Base):
    """Geladener Regelset-Stand für (Kanton, Gemeinde); `gemeinde` NULL = reines Kantonsset."""

    __tablename__ = "regelset"
    __table_args__ = (
        Index(
            "uq_regelset_scope_hash",
            "kanton",
            text("coalesce(gemeinde, '')"),
            "regelset_hash",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kanton: Mapped[Kanton] = mapped_column(_enum(Kanton, "kanton"))
    gemeinde: Mapped[str | None] = mapped_column(String(200))
    git_commit: Mapped[str] = mapped_column(String(100))
    regelset_hash: Mapped[str] = mapped_column(String(64))
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
    titel: Mapped[str] = mapped_column(String(500))
    pruefmethode: Mapped[str] = mapped_column(String(50))
    schwere: Mapped[str] = mapped_column(String(50))
    bedingung: Mapped[Any] = mapped_column(JSONB)
    anforderung: Mapped[dict[str, Any]] = mapped_column(JSONB)
    quelle: Mapped[dict[str, Any]] = mapped_column(JSONB)
    stand: Mapped[date] = mapped_column(Date)

    regelset: Mapped[Regelset] = relationship(back_populates="regeln")


class Pruefung(Base):
    """Prüflauf: hält Regelset-Hash und Modellversion fest, damit der Bericht reproduzierbar ist."""

    __tablename__ = "pruefung"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    buero_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buero.id"), index=True)
    dossier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dossier.id"), index=True)
    regelset_hash: Mapped[str] = mapped_column(String(64))
    modellversion: Mapped[str] = mapped_column(String(200))
    status: Mapped[Pruefstatus] = mapped_column(
        _enum(Pruefstatus, "pruefstatus"),
        default=Pruefstatus.LAEUFT,
        server_default=Pruefstatus.LAEUFT.value,
    )
    gestartet_am: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    beendet_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seiten_gesamt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    seiten_fertig: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Lease gegen parallele Ausführung: solange in der Zukunft, hält ein Worker den Lauf
    lauf_bis: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dossier: Mapped[Dossier] = relationship()
    befunde: Mapped[list["Befund"]] = relationship(
        back_populates="pruefung", cascade="all, delete-orphan", order_by="Befund.regel_id"
    )


class Befund(Base):
    __tablename__ = "befund"
    __table_args__ = (
        UniqueConstraint("pruefung_id", "regel_id"),
        CheckConstraint(
            "override_ergebnis IS NULL OR length(btrim(coalesce(override_begruendung, ''))) > 0",
            name="override_braucht_begruendung",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    buero_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buero.id"), index=True)
    pruefung_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pruefung.id"), index=True)
    regel_id: Mapped[str] = mapped_column(String(200))
    ergebnis: Mapped[Ergebnis] = mapped_column(_enum(Ergebnis, "ergebnis"))
    belege: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    override_ergebnis: Mapped[Ergebnis | None] = mapped_column(_enum(Ergebnis, "override_ergebnis"))
    override_begruendung: Mapped[str | None] = mapped_column(String(2000))
    override_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pruefung: Mapped[Pruefung] = relationship(back_populates="befunde")


class KiEinstellung(Base):
    """KI-Anbieter-Konfiguration der Installation (genau eine Zeile, `id = 1`).

    Bewusst nicht mandantengebunden: Anbieter und Schlüssel gelten für den ganzen Betrieb
    (ADR 0004) und sind nur für Superuser einsehbar. Der Schlüssel liegt verschlüsselt.
    """

    __tablename__ = "ki_einstellung"
    __table_args__ = (CheckConstraint("id = 1", name="ki_einstellung_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    modell: Mapped[str] = mapped_column(String(200), default="", server_default="")
    api_base: Mapped[str] = mapped_column(String(500), default="", server_default="")
    api_key_verschluesselt: Mapped[str] = mapped_column(String(2000), default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditEreignis(Base):
    """Nachvollziehbarkeit: nur IDs und Aktionscodes, nie Inhalte oder Personendaten."""

    __tablename__ = "audit_ereignis"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    buero_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column()
    aktion: Mapped[str] = mapped_column(String(100))
    objekt_typ: Mapped[str | None] = mapped_column(String(50))
    objekt_id: Mapped[uuid.UUID | None] = mapped_column()
    zeitpunkt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class LoginFehlversuch(Base):
    """Fehlversuch pro Schlüssel (SHA-256 von E-Mail bzw. IP) für Rate-Limit und Sperre."""

    __tablename__ = "login_fehlversuch"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    art: Mapped[str] = mapped_column(String(10))
    schluessel: Mapped[str] = mapped_column(String(64))
    zeitpunkt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_login_fehlversuch_art_schluessel", "art", "schluessel", "zeitpunkt"),
    )


# Denormalisiertes `buero_id` (Voraussetzung für RLS): wird beim Einfügen vom Elternobjekt
# übernommen, falls nicht gesetzt (z. B. bei Anlage über Relationships). `BueroScope` setzt es
# ausdrücklich.
_ELTERN: dict[type[Base], tuple[str, type[Base]]] = {
    Dokument: ("dossier_id", Dossier),
    Seite: ("dokument_id", Dokument),
    Pruefung: ("dossier_id", Dossier),
    Befund: ("pruefung_id", Pruefung),
}


def _buero_id_uebernehmen(mapper: Any, connection: Connection, target: Any) -> None:
    if target.buero_id is not None:
        return
    fk, eltern = _ELTERN[type(target)]
    target.buero_id = connection.scalar(
        select(eltern.buero_id).where(eltern.id == getattr(target, fk))  # type: ignore[attr-defined]
    )


for _modell in _ELTERN:
    event.listen(_modell, "before_insert", _buero_id_uebernehmen)


class Einladung(Base):
    """Einladung eines neuen Benutzers in ein Büro. Das Token wird nur gehasht gespeichert."""

    __tablename__ = "einladung"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    buero_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buero.id"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    rolle: Mapped[Rolle] = mapped_column(
        _enum(Rolle, "rolle"), default=Rolle.MITARBEITER, server_default=Rolle.MITARBEITER.value
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasswortReset(Base):
    """Einmaliges Reset-Token eines Benutzers (nur gehasht gespeichert)."""

    __tablename__ = "passwort_reset"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

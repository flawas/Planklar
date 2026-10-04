import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import Dossierstatus, Ergebnis, Kanton, Pruefstatus, Vorhabenstyp


class DokumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dossier_id: uuid.UUID
    dateiname: str
    sha256: str
    seitenzahl: int
    created_at: datetime


class _Attribute(BaseModel):
    """Gemeinsame Bezugsfelder (ja/nein); `None` = nicht angegeben."""

    model_config = ConfigDict(extra="forbid")

    verfahren: Literal["ordentlich", "vereinfacht"] | None = None
    gewaesserbezug: bool | None = None
    kantonsstrassenbezug: bool | None = None
    waldbezug: bool | None = None
    ausserhalb_bauzone: bool | None = None


class NeubauAttribute(_Attribute):
    gebaeudehoehe_m: float | None = Field(default=None, gt=0, le=200)
    heizsystem: str | None = Field(default=None, max_length=100)


class UmbauAttribute(_Attribute):
    gebaeudehoehe_m: float | None = Field(default=None, gt=0, le=200)
    heizsystem: str | None = Field(default=None, max_length=100)


class HeizungsersatzAttribute(_Attribute):
    heizsystem: str | None = Field(default=None, max_length=100)


ATTRIBUT_MODELLE: dict[Vorhabenstyp, type[_Attribute]] = {
    Vorhabenstyp.NEUBAU_EFH_MFH: NeubauAttribute,
    Vorhabenstyp.UMBAU_ANBAU: UmbauAttribute,
    Vorhabenstyp.HEIZUNGSERSATZ_WAERMEPUMPE: HeizungsersatzAttribute,
}


def validate_attribute(typ: Vorhabenstyp, attribute: dict[str, Any]) -> dict[str, Any]:
    """Prüft Attribute gegen das Modell des Vorhabenstyps; liefert nur gesetzte Felder."""
    return ATTRIBUT_MODELLE[typ].model_validate(attribute).model_dump(exclude_none=True)


def _gemeinde(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Gemeinde darf nicht leer sein")
    return value


class DossierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kanton: Kanton
    gemeinde: str = Field(max_length=200)
    vorhabenstyp: Vorhabenstyp
    attribute: dict[str, Any] = Field(default_factory=dict)

    _gemeinde = field_validator("gemeinde")(_gemeinde)

    @model_validator(mode="after")
    def _check_attribute(self) -> "DossierCreate":
        self.attribute = validate_attribute(self.vorhabenstyp, self.attribute)
        return self


class DossierUpdate(BaseModel):
    """Teilweise Änderung; `attribute` ersetzt die Attribute vollständig."""

    model_config = ConfigDict(extra="forbid")

    kanton: Kanton | None = None
    gemeinde: str | None = Field(default=None, max_length=200)
    vorhabenstyp: Vorhabenstyp | None = None
    attribute: dict[str, Any] | None = None

    _gemeinde = field_validator("gemeinde")(lambda v: v if v is None else _gemeinde(v))

    @model_validator(mode="after")
    def _no_nulls(self) -> "DossierUpdate":
        for name in ("kanton", "gemeinde", "vorhabenstyp", "attribute"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} darf nicht null sein")
        return self


class DossierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kanton: Kanton
    gemeinde: str
    vorhabenstyp: Vorhabenstyp
    attribute: dict[str, Any]
    status: Dossierstatus
    created_at: datetime


class PruefungRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dossier_id: uuid.UUID
    status: Pruefstatus
    regelset_hash: str
    modellversion: str
    gestartet_am: datetime
    beendet_am: datetime | None
    seiten_gesamt: int
    seiten_fertig: int


class BefundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    regel_id: str
    ergebnis: Ergebnis
    belege: list[str]
    override_ergebnis: Ergebnis | None
    override_begruendung: str | None
    override_am: datetime | None

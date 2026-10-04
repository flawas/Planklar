"""Typisierte Modelle für Regeldateien (Spiegel von rules/schema.json)."""

import datetime
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_URL_PATTERN = re.compile(r"^https?://\S+$")


class Kanton(StrEnum):
    LU = "LU"
    SZ = "SZ"


class Check(StrEnum):
    """Prüfmethode einer Regel."""

    KI_KLASSIFIKATION = "ki_klassifikation"
    FORMULARFELD = "formularfeld"
    PLAN_MERKMAL = "plan_merkmal"
    MANUELL = "manuell"


class Schwere(StrEnum):
    """Gewicht eines Befunds, wenn die Anforderung nicht erfüllt ist."""

    FEHLT_BLOCKIEREND = "fehlt_blockierend"
    HINWEIS = "hinweis"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Scope(_Strict):
    kanton: Kanton
    gemeinde: str | None = Field(default=None, min_length=1)


class Requires(BaseModel):
    """Anforderung; ausser `typ` sind weitere Felder je nach Typ erlaubt."""

    model_config = ConfigDict(extra="allow", frozen=True)

    typ: str = Field(min_length=1)


class Quelle(_Strict):
    erlass: str = Field(min_length=1)
    paragraph: str = Field(min_length=1)
    url: str

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        if not _URL_PATTERN.match(value):
            raise ValueError("url muss mit http:// oder https:// beginnen")
        return value


class Regel(_Strict):
    id: str
    titel: str = Field(min_length=1)
    scope: Scope
    when: dict[str, Any] | bool
    requires: Requires
    check: Check
    schwere: Schwere
    quelle: Quelle
    stand: datetime.date
    disabled: bool = False

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not _ID_PATTERN.match(value):
            raise ValueError("id darf nur Buchstaben, Ziffern, '_', '.' und '-' enthalten")
        return value


class KantonsRegeln(_Strict):
    """Alle Regeln eines Kantons: Basis (kanton.yaml) und Gemeinde-Dateien."""

    kanton: Kanton
    basis: tuple[Regel, ...]
    gemeinden: dict[str, tuple[Regel, ...]]

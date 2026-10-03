"""Normalisierung der PDF-Formularfelder auf feste Schlüssel (Zuordnung als Daten je Kanton)."""

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.pipeline.preprocess import extract_form_fields

MAPS_DIR = Path(__file__).parent / "field_maps"


class FormKey(StrEnum):
    BAUHERRSCHAFT = "bauherrschaft"
    PARZELLE = "parzelle"
    GEBAEUDETYP = "gebaeudetyp"


@dataclass(frozen=True)
class NormalizedFields:
    values: dict[str, str]  # Schlüssel -> Wert ('' = Feld vorhanden, aber leer)
    unmapped: list[str]  # Feldnamen ohne Zuordnung


def _norm(name: str) -> str:
    return name.strip().casefold()


def load_field_map(canton: str, maps_dir: Path = MAPS_DIR) -> dict[str, str]:
    """Feldname (normalisiert) -> Schlüssel. Unbekannte Schlüssel sind ein Datenfehler."""
    path = maps_dir / f"{canton.lower()}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for key, names in data["felder"].items():
        FormKey(key)  # ValueError bei unbekanntem Schlüssel
        for name in names:
            mapping[_norm(name)] = key
    return mapping


def normalize_fields(raw: dict[str, str], mapping: dict[str, str]) -> NormalizedFields:
    """Bei mehreren Feldern pro Schlüssel gewinnt das erste nicht-leere, sonst ''."""
    values: dict[str, str] = {}
    unmapped: list[str] = []
    for name, value in raw.items():
        key = mapping.get(_norm(name))
        if key is None:
            unmapped.append(name)
            continue
        if not values.get(key):
            values[key] = value.strip()
    return NormalizedFields(values, unmapped)


def extract_normalized_fields(
    source: Path | bytes, canton: str, maps_dir: Path = MAPS_DIR
) -> NormalizedFields:
    return normalize_fields(extract_form_fields(source), load_field_map(canton, maps_dir))

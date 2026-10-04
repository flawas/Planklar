"""Vererbung: effektives Regelset für (Kanton, Gemeinde) mit deterministischem Hash."""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.rules.loader import DEFAULT_ROOT, load_kanton
from app.rules.models import Kanton, KantonsRegeln, Regel


class Regelset(BaseModel):
    """Effektive Regeln, nach `id` sortiert, plus SHA-256 über die kanonische Form."""

    model_config = ConfigDict(frozen=True)

    kanton: Kanton
    gemeinde: str | None
    regeln: tuple[Regel, ...]
    hash: str


def regelset_hash(regeln: tuple[Regel, ...]) -> str:
    """SHA-256 über kanonisches JSON (nach `id` sortiert, Schlüssel sortiert)."""
    ordered = sorted(regeln, key=lambda r: r.id)
    canonical = json.dumps(
        [r.model_dump(mode="json") for r in ordered],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def merge(kanton: KantonsRegeln, gemeinde: str | None) -> Regelset:
    """Kantonsbasis; Gemeinde ergänzt, ersetzt bei gleicher `id` oder deaktiviert.

    Eine unbekannte Gemeinde ergibt das reine Kantonsset.
    """
    effektiv: dict[str, Regel] = {r.id: r for r in kanton.basis}
    for regel in kanton.gemeinden.get(gemeinde, ()) if gemeinde is not None else ():
        if regel.disabled:
            effektiv.pop(regel.id, None)
        else:
            effektiv[regel.id] = regel
    regeln = tuple(r for _, r in sorted(effektiv.items()) if not r.disabled)
    return Regelset(
        kanton=kanton.kanton, gemeinde=gemeinde, regeln=regeln, hash=regelset_hash(regeln)
    )


def resolve(kanton: Kanton, gemeinde: str | None = None, root: Path = DEFAULT_ROOT) -> Regelset:
    """Lädt den Katalog unter `root` und liefert das effektive Regelset."""
    return merge(load_kanton(root, kanton), gemeinde)

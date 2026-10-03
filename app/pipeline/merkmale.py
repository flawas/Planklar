"""Merkmals-Fragen je Plantyp: Zuordnung als Daten (`merkmale.json`), Prompts versioniert.

Das Ergebnis landet in `Seite.merkmale` und wird von der Regel-Engine konsumiert:

    {"massstab": {"status": "sicher", "vorhanden": "ja", "wert": "1:100",
                  "stimmen": 3, "einstimmig": true, "prompt": "merkmal_massstab_v1"},
     "nordpfeil": {"status": "unsicher", "vorhanden": null, "wert": null, ...},
     "_meta": {"model": "...", "plantyp": "Grundriss"}}

Nur `status == "sicher"` und `vorhanden == "ja"` darf die Engine als vorhanden werten;
alles andere ist `unsicher` bzw. nicht vorhanden. Die Pipeline entscheidet nie "erfüllt/fehlt".
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

from app.pipeline.extraction import Befund, extract_feature
from app.pipeline.llm import LLMClient
from app.pipeline.plantyp import Plantyp

_DIR = Path(__file__).parent
_PROMPTS = _DIR / "prompts"


@cache
def _config() -> dict[str, Any]:
    config: dict[str, Any] = json.loads((_DIR / "merkmale.json").read_text(encoding="utf-8"))
    return config


def merkmale_fuer(plantyp: Plantyp | str) -> tuple[str, ...]:
    """Merkmals-Ids, nach denen für diesen Plantyp gefragt wird."""
    return tuple(_config()["plantyp"].get(Plantyp(plantyp).value, ()))


def load_prompt(merkmal: str) -> str:
    version = _config()["merkmale"][merkmal]["prompt"]
    return (_PROMPTS / f"{version}.txt").read_text(encoding="utf-8").strip()


def schema_fuer(merkmal: str) -> dict[str, Any]:
    wert: dict[str, Any] = {"type": ["string", "null"]}
    return {
        "type": "object",
        "properties": {
            "vorhanden": {"type": "string", "enum": ["ja", "nein", "unklar"]},
            "wert": wert,
        },
        "required": ["vorhanden"]
        if not _config()["merkmale"][merkmal]["mit_wert"]
        else ["vorhanden", "wert"],
        "additionalProperties": False,
    }


def extract_merkmale(
    plantyp: Plantyp | str,
    image: bytes,
    *,
    client: LLMClient | None = None,
) -> dict[str, Any]:
    """Stellt je Merkmal des Plantyps eine enge Frage (3x, Mehrheit) zur einzelnen Seite."""
    result: dict[str, Any] = {}
    model: str | None = None
    for name in merkmale_fuer(plantyp):
        m = extract_feature(load_prompt(name), schema_fuer(name), image=image, client=client)
        model = m.model or model
        sicher = m.status is Befund.SICHER and isinstance(m.wert, dict)
        wert = m.wert.get("wert") if sicher else None
        if isinstance(wert, str):
            wert = wert.strip() or None
        status = m.status.value
        vorhanden = m.wert["vorhanden"] if sicher else None
        if vorhanden == "ja" and wert is None and _config()["merkmale"][name]["mit_wert"]:
            # «vorhanden» ohne lesbaren Wert: im Zweifel nie als vorhanden werten
            status, vorhanden = Befund.UNSICHER.value, None
        result[name] = {
            "status": status,
            "vorhanden": vorhanden,
            "wert": wert,
            "stimmen": m.stimmen,
            "einstimmig": m.einstimmig,
            "prompt": _config()["merkmale"][name]["prompt"],
        }
    result["_meta"] = {"model": model, "plantyp": Plantyp(plantyp).value}
    return result

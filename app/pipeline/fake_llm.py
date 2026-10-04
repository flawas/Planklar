"""Deterministischer Fake-Client für den End-to-End-Test im Compose-Stack (`LLM_MODEL=fake`).

Nie in Produktion verwenden: Er bestätigt jedes Merkmal, nur für synthetische Dossiers.
"""

import json
from collections.abc import Mapping
from typing import Any

from app.pipeline.llm import RawCompletion

FAKE_MODEL = "fake"


def complete(schema: Mapping[str, Any]) -> RawCompletion:
    props = schema.get("properties", {})
    if "plantyp" in props:  # Seitenklassifikation (Vision-Fallback)
        antwort: dict[str, Any] = {"plantyp": "Sonstiges", "konfidenz": 0.9}
    else:  # Merkmalsfrage
        antwort = {"vorhanden": "ja"}
        if "wert" in props:
            antwort["wert"] = "1:100"
    return RawCompletion(text=json.dumps(antwort), model=FAKE_MODEL)

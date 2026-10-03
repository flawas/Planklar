"""Merkmalsextraktion: jede enge Frage dreimal stellen, Mehrheit zählt.

Ohne Mehrheit (1:1:1, oder zu wenige gültige Antworten) ist das Ergebnis `unsicher`.
Die Pipeline entscheidet nie "erfüllt/fehlt"; sie liefert nur den Befund an die Regel-Engine.
"""

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.pipeline.llm import LLMClient, LLMResponseError, ask

VOTES = 3
MAJORITY = VOTES // 2 + 1


class Befund(StrEnum):
    SICHER = "sicher"
    UNSICHER = "unsicher"


@dataclass(frozen=True)
class Merkmal:
    """Ergebnis einer Dreifach-Abfrage. `wert` ist nur bei `SICHER` gesetzt."""

    status: Befund
    wert: Any
    stimmen: int  # Anzahl Antworten für den Mehrheitswert (0 bei unsicher)
    gueltig: int  # Anzahl schemakonformer Antworten
    einstimmig: bool
    model: str | None  # Modellversion, mit dem Ergebnis zu speichern


def _key(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def extract_feature(
    question: str,
    json_schema: Mapping[str, Any],
    *,
    image: bytes | None = None,
    text: str | None = None,
    image_mime: str = "image/png",
    client: LLMClient | None = None,
) -> Merkmal:
    """Stellt dieselbe enge Frage dreimal; Mehrheit (>= 2 gleiche gültige Antworten) zählt.

    Ungültige Antworten (kein JSON, Schemaverletzung) zählen als Abweichung.
    """
    answers = []
    for _ in range(VOTES):
        try:
            answers.append(
                ask(
                    question,
                    json_schema,
                    image=image,
                    text=text,
                    image_mime=image_mime,
                    client=client,
                )
            )
        except LLMResponseError:
            continue

    model = answers[-1].model if answers else None
    counts = Counter(_key(a.data) for a in answers)
    if counts:
        top_key, top = counts.most_common(1)[0]
        # Bei Gleichstand (z. B. 1:1 bei zwei gültigen Antworten) gibt es keine Mehrheit.
        if top >= MAJORITY:
            value = next(a.data for a in answers if _key(a.data) == top_key)
            return Merkmal(Befund.SICHER, value, top, len(answers), top == VOTES, model)
    return Merkmal(Befund.UNSICHER, None, 0, len(answers), False, model)

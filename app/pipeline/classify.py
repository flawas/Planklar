"""Seitenklassifikation: Text-Heuristik zuerst, Vision-Modell nur als Fallback.

Die Pipeline liefert nur Plantyp und Konfidenz; entschieden wird in der Regel-Engine.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from app.pipeline.llm import LLMClient, LLMError, ask
from app.pipeline.plantyp import Klassifikation, Plantyp, classify_text

PROMPT_VERSION = "klassifikation_vision_v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"
CONFIDENCE_THRESHOLD = 0.7
VOTES = 3  # jede Frage 3x, Mehrheit zählt

VISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "plantyp": {"type": "string", "enum": [t.value for t in Plantyp]},
        "konfidenz": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["plantyp", "konfidenz"],
    "additionalProperties": False,
}

_UNSURE = Klassifikation(Plantyp.SONSTIGES, 0.0)


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def classify_vision(image: bytes, *, client: LLMClient | None = None) -> Klassifikation:
    """Fragt das Vision-Modell 3x (eine Seite pro Aufruf). Ungültige Antwort oder
    uneinige Stimmen ergeben `Sonstiges` mit Konfidenz 0."""
    prompt = load_prompt()
    votes: list[tuple[Plantyp, float]] = []
    try:
        for _ in range(VOTES):
            data = ask(
                prompt, VISION_SCHEMA, image=image, client=client, zweck="klassifikation"
            ).data
            votes.append((Plantyp(data["plantyp"]), float(data["konfidenz"])))
    except LLMError:
        return _UNSURE
    typ, count = Counter(t for t, _ in votes).most_common(1)[0]
    if count <= VOTES // 2:
        return _UNSURE
    # Konservativ: niedrigste Konfidenz der Mehrheitsstimmen
    return Klassifikation(typ, min(k for t, k in votes if t == typ), (typ,))


def classify_page(
    text: str,
    image: bytes | None,
    *,
    threshold: float = CONFIDENCE_THRESHOLD,
    client: LLMClient | None = None,
) -> Klassifikation:
    """Heuristik; nur bei Konfidenz unter `threshold` zusätzlich das Vision-Modell."""
    heuristic = classify_text(text)
    if heuristic.konfidenz >= threshold or image is None:
        return heuristic
    return classify_vision(image, client=client)

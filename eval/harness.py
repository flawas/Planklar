"""Evaluations-Harness: lässt die Pipeline über annotierte Seiten laufen und misst Genauigkeit.

Bewertet wird Plantyp-Erkennung und Merkmalsextraktion. Ein falsches «erfüllt» (Pipeline
meldet etwas als vorhanden, das auf der Seite fehlt, oder einen falschen Plantyp) ist der
schwerste Fehler und hat ein eigenes Gate von 0.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.pipeline.classify import classify_page
from app.pipeline.llm import LLMClient
from app.pipeline.merkmale import _config as _merkmale_config
from app.pipeline.merkmale import extract_merkmale
from app.pipeline.plantyp import Plantyp

GATE_PLANTYP = 0.95
GATE_MERKMALE = 0.90
GATE_FALSCH_ERFUELLT = 0

PLANTYP_CHECK = "plantyp"


class DataError(Exception):
    """Evaluations-Set ist unvollständig oder ungültig."""


@dataclass(frozen=True)
class Seite:
    id: str
    bild: bytes
    plantyp: Plantyp
    merkmale: dict[str, dict[str, Any]]
    text: str = ""


@dataclass
class Tally:
    richtig: int = 0
    total: int = 0

    @property
    def genauigkeit(self) -> float:
        return self.richtig / self.total if self.total else 0.0


@dataclass
class Result:
    model: str
    seiten: int = 0
    checks: dict[str, Tally] = field(default_factory=lambda: defaultdict(Tally))
    falsch_erfuellt: list[str] = field(default_factory=list)

    @property
    def plantyp(self) -> float:
        return self.checks[PLANTYP_CHECK].genauigkeit

    @property
    def merkmale(self) -> float:
        tallies = [t for name, t in self.checks.items() if name != PLANTYP_CHECK]
        total = sum(t.total for t in tallies)
        return sum(t.richtig for t in tallies) / total if total else 0.0

    def gates(self) -> dict[str, bool]:
        return {
            "plantyp": self.plantyp >= GATE_PLANTYP,
            "merkmale": self.merkmale >= GATE_MERKMALE,
            "falsch_erfuellt": len(self.falsch_erfuellt) <= GATE_FALSCH_ERFUELLT,
        }

    @property
    def passed(self) -> bool:
        # Ohne bewertete Plantypen/Merkmale ist nichts belegt.
        return bool(self.seiten) and all(self.gates().values())


def _validate_merkmale(raw: Any) -> dict[str, dict[str, Any]]:
    """Annotationen strikt prüfen: ein Tippfehler darf das Gate nicht verfälschen."""
    if not isinstance(raw, dict):
        raise ValueError("merkmale")
    known = _merkmale_config()["merkmale"]
    for name, ann in raw.items():
        if name not in known or not isinstance(ann, dict):
            raise ValueError("merkmal")
        if ann.get("vorhanden") not in ("ja", "nein"):
            raise ValueError("vorhanden")
        if "wert" in ann and ann["vorhanden"] != "ja":
            raise ValueError("wert")
    return {name: dict(ann) for name, ann in raw.items()}


def load_seiten(directory: Path) -> list[Seite]:
    files = sorted(directory.glob("*.json"))
    seiten: list[Seite] = []
    for f in files:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            for entry in doc["seiten"]:
                bild = (f.parent / entry["bild"]).read_bytes()
                seiten.append(
                    Seite(
                        id=str(entry["id"]),
                        bild=bild,
                        plantyp=Plantyp(entry["plantyp"]),
                        merkmale=_validate_merkmale(entry.get("merkmale", {})),
                        text=str(entry.get("text", "")),
                    )
                )
        except (KeyError, ValueError, TypeError, OSError) as exc:
            # Nur Dateiname und Fehlerart, nie Inhalte
            raise DataError(f"{f.name}: ungültig ({type(exc).__name__})") from None
    if not seiten:
        raise DataError(f"Keine annotierten Seiten in {directory}")
    return seiten


def _norm(value: Any) -> str:
    return "".join(str(value).split()).lower() if value is not None else ""


def _merkmal_richtig(expected: dict[str, Any], got: dict[str, Any] | None) -> bool:
    """Nur `sicher` zählt als Treffer; `unsicher` ist nie richtig (aber nie falsch «erfüllt»)."""
    if got is None or got.get("status") != "sicher":
        return False
    if got.get("vorhanden") != expected["vorhanden"]:
        return False
    if expected["vorhanden"] == "ja" and "wert" in expected:
        return _norm(got.get("wert")) == _norm(expected["wert"])
    return True


def evaluate(seiten: list[Seite], *, model: str, client: LLMClient | None = None) -> Result:
    result = Result(model=model)
    for seite in seiten:
        result.seiten += 1
        klass = classify_page(seite.text, seite.bild, client=client)
        ok = klass.plantyp == seite.plantyp
        result.checks[PLANTYP_CHECK].total += 1
        result.checks[PLANTYP_CHECK].richtig += ok
        if not ok and klass.plantyp is not Plantyp.SONSTIGES:
            result.falsch_erfuellt.append(f"{seite.id}:plantyp")

        # Merkmale werden am erkannten Plantyp bemessen, wie im Betrieb.
        got = extract_merkmale(klass.plantyp, seite.bild, client=client)
        for name, expected in sorted(seite.merkmale.items()):
            tally = result.checks[name]
            tally.total += 1
            tally.richtig += _merkmal_richtig(expected, got.get(name))
            g = got.get(name) or {}
            if (
                expected["vorhanden"] != "ja"
                and g.get("status") == "sicher"
                and g.get("vorhanden") == "ja"
            ):
                result.falsch_erfuellt.append(f"{seite.id}:{name}")
    return result


def to_json(result: Result) -> dict[str, Any]:
    return {
        "model": result.model,
        "seiten": result.seiten,
        "genauigkeit": {
            "plantyp": result.plantyp,
            "merkmale": result.merkmale,
            "pro_pruefung": {
                name: {"richtig": t.richtig, "total": t.total, "genauigkeit": t.genauigkeit}
                for name, t in sorted(result.checks.items())
            },
        },
        "falsch_erfuellt": result.falsch_erfuellt,
        "gates": result.gates(),
        "bestanden": result.passed,
    }


def to_markdown(result: Result) -> str:
    gates = result.gates()
    mark = {True: "bestanden", False: "NICHT bestanden"}
    lines = [
        f"# Evaluation – Modell `{result.model}`",
        "",
        f"Seiten: {result.seiten}. Gesamt: **{mark[result.passed]}**.",
        "",
        "| Gate | Wert | Ziel | Status |",
        "|---|---|---|---|",
        f"| Plantyp | {result.plantyp:.1%} | >= {GATE_PLANTYP:.0%} | {mark[gates['plantyp']]} |",
        f"| Merkmale | {result.merkmale:.1%} | >= {GATE_MERKMALE:.0%} "
        f"| {mark[gates['merkmale']]} |",
        f"| Falsche «erfüllt» | {len(result.falsch_erfuellt)} | {GATE_FALSCH_ERFUELLT} "
        f"| {mark[gates['falsch_erfuellt']]} |",
        "",
        "## Genauigkeit pro Prüfung",
        "",
        "| Prüfung | Richtig | Total | Genauigkeit |",
        "|---|---|---|---|",
    ]
    for name, t in sorted(result.checks.items()):
        lines.append(f"| {name} | {t.richtig} | {t.total} | {t.genauigkeit:.1%} |")
    if result.falsch_erfuellt:
        lines += ["", "## Falsche «erfüllt»", ""]
        lines += [f"- {entry}" for entry in result.falsch_erfuellt]
    return "\n".join(lines) + "\n"

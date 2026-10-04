"""Erzeugt das synthetische Evaluations-Set aus den Beispielplänen (Weggis, Küssnacht).

Aufruf: python -m eval.make_synthetic_set
Rendert jede Seite als PNG und schreibt `eval/data/synthetisch.json`. Der Text bleibt leer,
damit die Klassifikation das Vision-Modell statt der Text-Heuristik prüft. `unterschrift`
wird nicht annotiert (die Pläne tragen nur eine Beschriftung, keine echte Unterschrift).
"""

import json
from pathlib import Path

import pymupdf

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures" / "beispielplaene"
OUT = Path(__file__).parent / "data"

PROJEKTE = {
    "weggis": ("weggis_baugesuch_plaene.pdf", "Beispiel Architektur AG"),
    "kuessnacht": ("kuessnacht_baugesuch_plaene.pdf", "Entwurf Planung GmbH"),
}

# Seite -> (Plantyp, Massstab, Nordpfeil, Legende)
SEITEN = [
    ("Situationsplan", "1:500", True, None),
    ("Grundriss", "1:100", True, False),
    ("Grundriss", "1:100", True, False),
    ("Fassade/Ansicht", "1:100", None, False),
    ("Schnitt", "1:100", None, False),
]


def _ja(wert: str | None = None) -> dict[str, str]:
    return {"vorhanden": "ja", **({"wert": wert} if wert else {})}


def main() -> None:
    seiten = []
    for slug, (pdf, verfasser) in PROJEKTE.items():
        doc = pymupdf.open(FIXTURES / pdf)
        for i, (plantyp, massstab, nord, legende) in enumerate(SEITEN):
            bild = f"{slug}-s{i + 1}.png"
            doc[i].get_pixmap(dpi=100).save(OUT / bild)
            merkmale = {
                "massstab": _ja(massstab),
                "datum": _ja("01.10.2026"),
                "planverfasser": _ja(verfasser),
            }
            if nord is not None:
                merkmale["nordpfeil"] = _ja()
            if legende is False:
                merkmale["legende_farbcodierung"] = {"vorhanden": "nein"}
            seiten.append(
                {
                    "id": f"{slug}-s{i + 1}",
                    "bild": bild,
                    "text": "",
                    "plantyp": plantyp,
                    "merkmale": merkmale,
                }
            )
    (OUT / "synthetisch.json").write_text(
        json.dumps({"seiten": seiten}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(len(seiten), "Seiten geschrieben")


if __name__ == "__main__":
    main()

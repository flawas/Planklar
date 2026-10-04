"""Erzeugt synthetische Beispielpläne für Weggis (LU) und Küssnacht (SZ) fürs manuelle GUI-Testen.

Aufruf: python tests/fixtures/make_beispielplaene.py
Frei erfundene Projekte (keine echten Baugesuche); Plankopf mit Plannummer, Datum, Massstab.
"""

from dataclasses import dataclass
from pathlib import Path

import pymupdf

OUT = Path(__file__).parent / "beispielplaene"
A3 = pymupdf.paper_rect("a3-l")


@dataclass(frozen=True)
class Projekt:
    gemeinde: str
    kanton: str
    strasse: str
    parzelle: str
    bauherr: str
    architekt: str
    datum: str


PROJEKTE = [
    Projekt(
        "Weggis",
        "LU",
        "Musterweg 12",
        "Nr. 1234",
        "Muster Immobilien AG",
        "Beispiel Architektur AG",
        "01.10.2026",
    ),
    Projekt(
        "Küssnacht am Rigi",
        "SZ",
        "Beispielstrasse 5",
        "Nr. 5678",
        "Anna und Hans Muster",
        "Entwurf Planung GmbH",
        "01.10.2026",
    ),
]


def _plankopf(page: pymupdf.Page, p: Projekt, nummer: str, titel: str, massstab: str) -> None:
    r = pymupdf.Rect(A3.width - 330, A3.height - 150, A3.width - 20, A3.height - 20)
    page.draw_rect(r, width=1)
    zeilen = [
        f"Neubau Einfamilienhaus, {p.strasse}",
        f"{p.gemeinde} ({p.kanton}), Parzelle {p.parzelle}",
        f"Bauherrschaft: {p.bauherr}",
        f"Planverfasser: {p.architekt}",
        f"Plan {nummer}: {titel}",
        f"Massstab {massstab}   Datum {p.datum}",
    ]
    for i, z in enumerate(zeilen):
        page.insert_text((r.x0 + 8, r.y0 + 18 + i * 17), z, fontsize=9)
    page.insert_text(
        (r.x0 + 8, r.y1 - 6),
        "Unterschriften: Bauherrschaft / Planverfasser / Grundeigentümer",
        fontsize=6,
    )


def _nordpfeil(page: pymupdf.Page, x: float, y: float) -> None:
    page.draw_line((x, y + 40), (x, y), width=1.5)
    page.draw_polyline([(x - 6, y + 12), (x, y), (x + 6, y + 12)], width=1.5)
    page.insert_text((x - 3, y - 4), "N", fontsize=10)


def _bemasst(page: pymupdf.Page, rect: pymupdf.Rect, breite: str, tiefe: str) -> None:
    page.insert_text((rect.x0 + rect.width / 2 - 12, rect.y0 - 8), breite, fontsize=9)
    page.insert_text((rect.x0 - 38, rect.y0 + rect.height / 2), tiefe, fontsize=9)


def situationsplan(p: Projekt) -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=A3.width, height=A3.height)
    parzelle = pymupdf.Rect(150, 120, 700, 520)
    page.draw_rect(parzelle, width=1.5, dashes="[6 3] 0")
    page.insert_text(
        (parzelle.x0 + 8, parzelle.y0 + 18), f"Parzelle {p.parzelle}  Fläche 812 m²", fontsize=10
    )
    haus = pymupdf.Rect(300, 230, 520, 370)
    page.draw_rect(haus, width=2, fill=(0.85, 0.85, 0.85))
    page.insert_text(
        (haus.x0 + 20, haus.y0 + 70), "Neubau EFH, Gebäudegrundfläche 154 m²", fontsize=9
    )
    _bemasst(page, haus, "11.00", "14.00")
    nachbar = pymupdf.Rect(760, 200, 900, 330)
    page.draw_rect(nachbar, width=1)
    page.insert_text((nachbar.x0 + 10, nachbar.y0 + 70), "best. Nachbargebäude", fontsize=8)
    page.draw_line((0, 570), (A3.width, 570), width=6, color=(0.5, 0.5, 0.5))
    page.insert_text((200, 595), p.strasse.split()[0] + " (Erschliessungsstrasse)", fontsize=10)
    page.insert_text(
        (parzelle.x0, parzelle.y1 + 14),
        "Grenzabstand 4.00 m, Strassenabstand 6.00 m (Angaben zur Situation)",
        fontsize=8,
    )
    _nordpfeil(page, 860, 450)
    _plankopf(page, p, "01", "Situationsplan", "1:500")
    return doc


def grundriss(p: Projekt, nummer: str, geschoss: str) -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=A3.width, height=A3.height)
    aussen = pymupdf.Rect(150, 130, 590, 410)
    page.draw_rect(aussen, width=3)
    page.draw_line((aussen.x0 + 260, aussen.y0), (aussen.x0 + 260, aussen.y1), width=1.5)
    page.draw_line((aussen.x0, aussen.y0 + 150), (aussen.x0 + 260, aussen.y0 + 150), width=1.5)
    raeume = {
        "EG": [
            ("Wohnen/Essen", 30, 40, "38.5 m²"),
            ("Küche", 30, 200, "14.2 m²"),
            ("Eingang/WC", 290, 60, "12.0 m²"),
            ("Garderobe", 290, 200, "8.5 m²"),
        ],
        "OG": [
            ("Zimmer 1", 30, 40, "16.0 m²"),
            ("Zimmer 2", 30, 200, "14.5 m²"),
            ("Bad", 290, 60, "9.0 m²"),
            ("Elternzimmer", 290, 200, "18.0 m²"),
        ],
    }[geschoss]
    for name, dx, dy, flaeche in raeume:
        page.insert_text((aussen.x0 + dx, aussen.y0 + dy), name, fontsize=10)
        page.insert_text(
            (aussen.x0 + dx, aussen.y0 + dy + 12), f"BGF {flaeche}  FF 2.4 m²", fontsize=7
        )
    _bemasst(page, aussen, "11.00", "7.00")
    page.draw_line(
        (aussen.x0 + 130, aussen.y0 - 30),
        (aussen.x0 + 130, aussen.y1 + 30),
        width=0.8,
        dashes="[8 3 2 3] 0",
    )
    page.insert_text((aussen.x0 + 126, aussen.y0 - 36), "A", fontsize=10)
    page.insert_text((aussen.x0 + 126, aussen.y1 + 42), "A", fontsize=10)
    page.insert_text(
        (aussen.x0, aussen.y1 + 70),
        f"Grundriss {geschoss}, OK FFB {'±0.00 = 456.40 m ü. M.' if geschoss == 'EG' else '+2.80'}",
        fontsize=10,
    )
    page.insert_text(
        (aussen.x0, aussen.y1 + 85),
        "Fensterflächen gemäss Raumstempel, Wandstärke Aussenwand 36 cm",
        fontsize=8,
    )
    _nordpfeil(page, 850, 160)
    _plankopf(page, p, nummer, f"Grundriss {geschoss}", "1:100")
    return doc


def fassaden(p: Projekt) -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=A3.width, height=A3.height)
    for i, name in enumerate(("Südfassade", "Nordfassade")):
        x0, y0 = 120 + i * 400, 150
        page.draw_rect(pymupdf.Rect(x0, y0 + 90, x0 + 330, y0 + 280), width=2)
        page.draw_polyline([(x0 - 15, y0 + 90), (x0 + 165, y0), (x0 + 345, y0 + 90)], width=2)
        for fx in (40, 140, 240):
            page.draw_rect(pymupdf.Rect(x0 + fx, y0 + 130, x0 + fx + 50, y0 + 190), width=1)
            page.draw_rect(pymupdf.Rect(x0 + fx, y0 + 215, x0 + fx + 50, y0 + 270), width=1)
        page.draw_line((x0 - 30, y0 + 280), (x0 + 360, y0 + 280), width=1.5)
        page.insert_text(
            (x0, y0 + 305),
            f"{name}  Firsthöhe +8.20 m, Gebäudehöhe 6.40 m, Terrain neu/best.",
            fontsize=9,
        )
    _plankopf(page, p, "05", "Fassaden Süd und Nord", "1:100")
    return doc


def schnitt(p: Projekt) -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=A3.width, height=A3.height)
    x0, y0 = 160, 150
    page.draw_rect(pymupdf.Rect(x0, y0 + 90, x0 + 330, y0 + 280), width=2)
    page.draw_polyline([(x0 - 15, y0 + 90), (x0 + 165, y0), (x0 + 345, y0 + 90)], width=2)
    page.draw_line((x0, y0 + 190), (x0 + 330, y0 + 190), width=1.5)
    page.draw_line((x0 - 80, y0 + 280), (x0 + 410, y0 + 280), width=2, color=(0.4, 0.2, 0))
    page.draw_line((x0 - 80, y0 + 250), (x0, y0 + 280), width=1, dashes="[4 3] 0")
    page.insert_text(
        (x0, y0 + 320),
        "Schnitt A-A  Geschosshöhen 2.60 m, UK Fundament 453.20 m ü. M., Terrain gestrichelt",
        fontsize=9,
    )
    page.insert_text(
        (x0, y0 + 335),
        "Aufbau Dach: Ziegel, Lattung, Unterdach, Sparren; Decke Stahlbeton 22 cm",
        fontsize=8,
    )
    _plankopf(page, p, "06", "Schnitt A-A", "1:100")
    return doc


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for p in PROJEKTE:
        slug = p.gemeinde.split()[0].lower().replace("ü", "ue")
        gesamt = pymupdf.open()
        for d in (
            situationsplan(p),
            grundriss(p, "02", "EG"),
            grundriss(p, "03", "OG"),
            fassaden(p),
            schnitt(p),
        ):
            gesamt.insert_pdf(d)
        gesamt.save(OUT / f"{slug}_baugesuch_plaene.pdf")
        print(OUT / f"{slug}_baugesuch_plaene.pdf", len(gesamt), "Seiten")


if __name__ == "__main__":
    main()

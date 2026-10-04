"""Erzeugt die synthetischen Test-PDFs (keine echten Baugesuche)."""

from pathlib import Path

import pymupdf

HERE = Path(__file__).parent


def make_mixed(path: Path) -> None:
    """Seite 1 mit Text, Seite 2 nur Bild (kein Textlayer)."""
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Synthetisches Baugesuch Seite eins")
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(72, 72, 200, 200), pixmap=pix)
    doc.save(path)


def make_scanned(path: Path) -> None:
    """Eine Seite, deren Text nur als Bild vorliegt (kein Textlayer)."""
    src = pymupdf.open()
    src.new_page().insert_text((72, 100), "Baugesuch Situationsplan", fontsize=28)
    pix = src[0].get_pixmap(dpi=200)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=pix)
    doc.save(path)


def make_form(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    for i, (name, value) in enumerate([("bauherr", "Muster AG"), ("parzelle", "")]):
        w = pymupdf.Widget()
        w.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        w.field_name = name
        w.field_value = value
        w.rect = pymupdf.Rect(72, 72 + 40 * i, 300, 92 + 40 * i)
        page.add_widget(w)
    doc.save(path)


if __name__ == "__main__":
    make_mixed(HERE / "mixed.pdf")
    make_scanned(HERE / "scanned.pdf")
    make_form(HERE / "form.pdf")

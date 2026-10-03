"""PDF-Vorverarbeitung: Seiten, Textlayer und Formularfelder (reine Funktionen)."""

from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass(frozen=True)
class PageText:
    number: int  # 1-basiert
    text: str
    has_text_layer: bool


@dataclass(frozen=True)
class PdfContent:
    page_count: int
    pages: list[PageText]
    form_fields: dict[str, str]

    @property
    def pages_without_text_layer(self) -> list[int]:
        return [p.number for p in self.pages if not p.has_text_layer]


def open_pdf(source: Path | bytes) -> pymupdf.Document:
    if isinstance(source, bytes):
        return pymupdf.open(stream=source, filetype="pdf")
    return pymupdf.open(source)


def extract_pages(source: Path | bytes) -> list[PageText]:
    """Text je Seite; eine Seite ohne nicht-leeren Text gilt als ohne Textlayer."""
    with open_pdf(source) as doc:
        pages: list[PageText] = []
        for index, page in enumerate(doc):
            text = str(page.get_text("text"))
            pages.append(PageText(index + 1, text, bool(text.strip())))
        return pages


def extract_form_fields(source: Path | bytes) -> dict[str, str]:
    """PDF-Formularfelder (AcroForm) als Name -> Wert; leere Werte als ''."""
    with open_pdf(source) as doc:
        fields: dict[str, str] = {}
        for page in doc:
            for widget in page.widgets() or []:
                value = widget.field_value
                fields[widget.field_name] = "" if value is None else str(value)
        return fields


def preprocess(source: Path | bytes) -> PdfContent:
    pages = extract_pages(source)
    return PdfContent(len(pages), pages, extract_form_fields(source))

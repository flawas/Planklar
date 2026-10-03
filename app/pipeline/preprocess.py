"""PDF-Vorverarbeitung: Seiten, Textlayer und Formularfelder (reine Funktionen)."""

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.pipeline.ocr import ocr_page, tesseract_available


@dataclass(frozen=True)
class PageText:
    number: int  # 1-basiert
    text: str
    has_text_layer: bool
    ocr_used: bool = False


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


def extract_pages(source: Path | bytes, ocr: bool = True) -> list[PageText]:
    """Text je Seite; eine Seite ohne nicht-leeren Text gilt als ohne Textlayer.

    Solche Seiten laufen durch den OCR-Fallback (Tesseract, deu), sofern `ocr` gesetzt und
    Tesseract verfügbar ist. `has_text_layer` bleibt False, `ocr_used` markiert den Fallback.
    """
    use_ocr = ocr and tesseract_available()
    with open_pdf(source) as doc:
        pages: list[PageText] = []
        for index, page in enumerate(doc):
            text = str(page.get_text("text"))
            has_layer = bool(text.strip())
            if has_layer or not use_ocr:
                pages.append(PageText(index + 1, text, has_layer))
            else:
                pages.append(PageText(index + 1, ocr_page(page), False, ocr_used=True))
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


def preprocess(source: Path | bytes, ocr: bool = True) -> PdfContent:
    pages = extract_pages(source, ocr=ocr)
    return PdfContent(len(pages), pages, extract_form_fields(source))

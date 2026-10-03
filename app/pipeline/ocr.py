"""OCR-Fallback für Seiten ohne Textlayer (Tesseract, Sprache deu)."""

import shutil
from pathlib import Path

import pymupdf

OCR_LANGUAGE = "deu"
OCR_DPI = 200


def tesseract_available() -> bool:
    """True, wenn das Tesseract-Binary und die Sprachdaten `deu` vorhanden sind."""
    if shutil.which("tesseract") is None:
        return False
    try:
        tessdata = pymupdf.get_tessdata()
    except Exception:
        return False
    return bool(tessdata) and (Path(tessdata) / f"{OCR_LANGUAGE}.traineddata").is_file()


def ocr_page(page: pymupdf.Page) -> str:
    """Text einer einzelnen Seite per OCR (Seite wird mit 200 dpi gerendert)."""
    textpage = page.get_textpage_ocr(language=OCR_LANGUAGE, dpi=OCR_DPI, full=True)
    return str(page.get_text("text", textpage=textpage))

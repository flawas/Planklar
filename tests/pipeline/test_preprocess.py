from pathlib import Path

import pytest

from app.pipeline.ocr import tesseract_available
from app.pipeline.preprocess import extract_form_fields, extract_pages, preprocess

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_page_count_and_text() -> None:
    content = preprocess(FIXTURES / "mixed.pdf")
    assert content.page_count == 2
    assert "Baugesuch" in content.pages[0].text
    assert content.pages[0].number == 1


def test_page_without_text_layer_detected() -> None:
    content = preprocess(FIXTURES / "mixed.pdf")
    assert [p.has_text_layer for p in content.pages] == [True, False]
    assert content.pages_without_text_layer == [2]


def test_form_fields_as_dict() -> None:
    assert extract_form_fields(FIXTURES / "form.pdf") == {"bauherr": "Muster AG", "parzelle": ""}


def test_no_form_fields() -> None:
    assert extract_form_fields(FIXTURES / "mixed.pdf") == {}


def test_accepts_bytes() -> None:
    data = (FIXTURES / "mixed.pdf").read_bytes()
    assert len(extract_pages(data)) == 2


needs_tesseract = pytest.mark.skipif(not tesseract_available(), reason="Tesseract (deu) fehlt")


@needs_tesseract
def test_ocr_fallback_for_scanned_page() -> None:
    page = preprocess(FIXTURES / "scanned.pdf").pages[0]
    assert page.ocr_used
    assert not page.has_text_layer
    assert "Baugesuch" in page.text
    assert "Situationsplan" in page.text


@needs_tesseract
def test_text_layer_page_not_ocrd() -> None:
    pages = preprocess(FIXTURES / "mixed.pdf").pages
    assert [p.ocr_used for p in pages[:1]] == [False]
    assert "Baugesuch" in pages[0].text


def test_ocr_can_be_disabled() -> None:
    page = preprocess(FIXTURES / "scanned.pdf", ocr=False).pages[0]
    assert page.text.strip() == ""
    assert not page.ocr_used

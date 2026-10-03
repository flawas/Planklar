from pathlib import Path

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

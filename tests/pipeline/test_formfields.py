import json
from pathlib import Path

import pytest

from app.pipeline.formfields import (
    extract_normalized_fields,
    load_field_map,
    normalize_fields,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _write_map(tmp_path: Path, canton: str, felder: dict[str, list[str]]) -> Path:
    (tmp_path / f"{canton}.json").write_text(json.dumps({"kanton": canton, "felder": felder}))
    return tmp_path


def test_synthetic_form_normalized(tmp_path: Path) -> None:
    maps = _write_map(tmp_path, "xx", {"bauherrschaft": ["Bauherr"], "parzelle": ["parzelle"]})
    result = extract_normalized_fields(FIXTURES / "form.pdf", "xx", maps)
    assert result.values == {"bauherrschaft": "Muster AG", "parzelle": ""}
    assert result.unmapped == []


def test_mapping_is_per_canton_data(tmp_path: Path) -> None:
    _write_map(tmp_path, "aa", {"bauherrschaft": ["bauherr"]})
    _write_map(tmp_path, "bb", {"parzelle": ["bauherr"]})
    assert load_field_map("aa", tmp_path) == {"bauherr": "bauherrschaft"}
    assert load_field_map("BB", tmp_path) == {"bauherr": "parzelle"}


def test_unmapped_fields_reported() -> None:
    result = normalize_fields({"x": "1", "bauherr": "A"}, {"bauherr": "bauherrschaft"})
    assert result.values == {"bauherrschaft": "A"}
    assert result.unmapped == ["x"]


def test_first_non_empty_value_wins() -> None:
    mapping = {"a": "parzelle", "b": "parzelle"}
    assert normalize_fields({"a": "", "b": " 12 "}, mapping).values == {"parzelle": "12"}


def test_unknown_key_rejected(tmp_path: Path) -> None:
    _write_map(tmp_path, "cc", {"unbekannt": ["f"]})
    with pytest.raises(ValueError):
        load_field_map("cc", tmp_path)


@pytest.mark.parametrize("canton", ["lu", "sz"])
def test_shipped_maps_load(canton: str) -> None:
    assert isinstance(load_field_map(canton), dict)

from pathlib import Path

import pytest
import yaml

from app.rules.loader import RegelLadeFehler, load_catalog, load_file, load_kanton
from app.rules.models import Check, Kanton, Schwere

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rules" / "loader"

RULE = {
    "id": "TEST-1",
    "titel": "Beispiel",
    "scope": {"kanton": "LU"},
    "when": True,
    "requires": {"typ": "dokument"},
    "check": "manuell",
    "schwere": "fehlt_blockierend",
    "quelle": {"erlass": "E", "paragraph": "§ 1", "url": "https://example.org"},
    "stand": "2026-01-01",
}


def _write(tmp_path: Path, rules: object, name: str = "kanton.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(rules), encoding="utf-8")
    return path


def test_loads_kanton_and_gemeinden_typed() -> None:
    lu = load_kanton(FIXTURES / "ok", Kanton.LU)
    assert lu.kanton is Kanton.LU
    (basis,) = lu.basis
    assert basis.check is Check.KI_KLASSIFIKATION
    assert basis.schwere is Schwere.FEHLT_BLOCKIEREND
    assert basis.requires.typ == "dokument"
    assert basis.requires.model_extra == {"dokument": "situationsplan"}
    (override,) = lu.gemeinden["Beispielhausen"]
    assert override.disabled is True
    assert override.id == basis.id


def test_load_catalog_only_existing_cantons() -> None:
    assert set(load_catalog(FIXTURES / "ok")) == {Kanton.LU}


def test_real_catalog_loads() -> None:
    load_catalog()


def test_enums_cover_schema() -> None:
    assert {c.value for c in Check} == {
        "ki_klassifikation",
        "formularfeld",
        "plan_merkmal",
        "manuell",
    }


def test_missing_kanton_yaml_names_file() -> None:
    with pytest.raises(RegelLadeFehler, match=r"kanton\.yaml") as exc:
        load_kanton(FIXTURES / "no_basis", Kanton.SZ)
    assert exc.value.path.name == "kanton.yaml"


def test_broken_yaml_names_file(tmp_path: Path) -> None:
    path = tmp_path / "kanton.yaml"
    path.write_text("- id: [", encoding="utf-8")
    with pytest.raises(RegelLadeFehler, match="ungültiges YAML") as exc:
        load_file(path, Kanton.LU)
    assert str(path) in str(exc.value)


def test_invalid_check_names_file_and_rule_id(tmp_path: Path) -> None:
    path = _write(tmp_path, [{**RULE, "check": "zauberei"}])
    with pytest.raises(RegelLadeFehler) as exc:
        load_file(path, Kanton.LU)
    assert exc.value.regel_id == "TEST-1"
    assert str(path) in str(exc.value)
    assert "TEST-1" in str(exc.value)
    assert "check" in str(exc.value)


@pytest.mark.parametrize("field", ["quelle", "stand", "schwere", "scope"])
def test_missing_field_reported(tmp_path: Path, field: str) -> None:
    rule = {k: v for k, v in RULE.items() if k != field}
    with pytest.raises(RegelLadeFehler, match=field):
        load_file(_write(tmp_path, [rule]), Kanton.LU)


def test_rule_without_id_reports_position(tmp_path: Path) -> None:
    rule = {k: v for k, v in RULE.items() if k != "id"}
    with pytest.raises(RegelLadeFehler, match="Eintrag 1"):
        load_file(_write(tmp_path, [rule]), Kanton.LU)


def test_bad_url_and_unknown_field_rejected(tmp_path: Path) -> None:
    bad_url = {**RULE, "quelle": {**RULE["quelle"], "url": "ftp://x"}}
    with pytest.raises(RegelLadeFehler, match="url"):
        load_file(_write(tmp_path, [bad_url]), Kanton.LU)
    with pytest.raises(RegelLadeFehler, match="foo: Extra inputs"):
        load_file(_write(tmp_path, [{**RULE, "foo": 1}]), Kanton.LU)


def test_not_a_list_rejected(tmp_path: Path) -> None:
    with pytest.raises(RegelLadeFehler, match="Liste"):
        load_file(_write(tmp_path, {"id": "x"}), Kanton.LU)


def test_scope_must_match_location(tmp_path: Path) -> None:
    path = _write(tmp_path, [RULE])
    with pytest.raises(RegelLadeFehler, match="passt nicht zu"):
        load_file(path, Kanton.SZ)
    gem = {**RULE, "scope": {"kanton": "LU", "gemeinde": "X"}}
    with pytest.raises(RegelLadeFehler, match="keine scope.gemeinde"):
        load_file(_write(tmp_path, [gem], "gem.yaml"), Kanton.LU)
    with pytest.raises(RegelLadeFehler, match="braucht scope.gemeinde"):
        load_file(path, Kanton.LU, gemeinde_datei=True)


def test_duplicate_id_in_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(RegelLadeFehler, match="doppelte id") as exc:
        load_file(_write(tmp_path, [RULE, RULE]), Kanton.LU)
    assert exc.value.regel_id == "TEST-1"

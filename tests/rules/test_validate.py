from pathlib import Path

import pytest

from app.rules.validate import DEFAULT_ROOT, main, validate_catalog

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rules"
INVALID = sorted(p.name for p in (FIXTURES / "invalid").iterdir())


def test_valid_fixtures_pass() -> None:
    assert validate_catalog(FIXTURES / "valid") == []
    assert main([str(FIXTURES / "valid")]) == 0


@pytest.mark.parametrize("name", INVALID)
def test_invalid_fixtures_fail(name: str) -> None:
    root = FIXTURES / "invalid" / name
    assert validate_catalog(root)
    assert main([str(root)]) != 0


def test_duplicate_id_reported() -> None:
    errors = validate_catalog(FIXTURES / "invalid" / "duplicate_id")
    assert any("doppelte id" in e for e in errors)


def test_missing_quelle_and_stand_reported() -> None:
    assert any("quelle" in e for e in validate_catalog(FIXTURES / "invalid" / "missing_quelle"))
    assert any("stand" in e for e in validate_catalog(FIXTURES / "invalid" / "missing_stand"))


def test_same_id_in_different_scope_is_allowed() -> None:
    assert validate_catalog(FIXTURES / "valid") == []


def test_real_catalog_is_valid() -> None:
    assert validate_catalog(DEFAULT_ROOT) == []


def test_missing_directory_exit_code() -> None:
    assert main(["/nonexistent/path"]) == 2

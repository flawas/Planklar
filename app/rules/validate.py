"""Validiert alle YAML-Regeldateien unter einem Verzeichnis gegen rules/schema.json.

Aufruf: python -m app.rules.validate [Verzeichnis]
"""

import datetime
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "rules"
SCHEMA_PATH = DEFAULT_ROOT / "schema.json"


def _normalize(value: Any) -> Any:
    """YAML liest Daten als date; das Schema erwartet ISO-Strings."""
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _load_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return schema


def validate_file(path: Path, validator: Draft202012Validator) -> list[str]:
    try:
        data = _normalize(yaml.safe_load(path.read_text(encoding="utf-8")))
    except yaml.YAMLError as exc:
        return [f"{path}: ungültiges YAML: {exc}"]
    errors = [
        f"{path}: {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.path)))
    ]
    return errors


def _scope_key(rule: dict[str, Any]) -> tuple[str, str | None]:
    scope = rule["scope"]
    return scope["kanton"], scope.get("gemeinde")


def validate_catalog(root: Path) -> list[str]:
    """Gibt alle Fehler als Liste zurück; leer bedeutet gültig."""
    validator = Draft202012Validator(
        _load_schema(), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    errors: list[str] = []
    seen: dict[tuple[tuple[str, str | None], str], Path] = {}
    files = sorted([*root.rglob("*.yaml"), *root.rglob("*.yml")])
    for path in files:
        file_errors = validate_file(path, validator)
        errors.extend(file_errors)
        if file_errors:
            continue
        for rule in _normalize(yaml.safe_load(path.read_text(encoding="utf-8"))):
            key = (_scope_key(rule), rule["id"])
            if key in seen:
                errors.append(
                    f"{path}: doppelte id '{rule['id']}' im Scope {key[0]} (zuerst in {seen[key]})"
                )
            else:
                seen[key] = path
    return errors


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]) if args else DEFAULT_ROOT
    if not root.is_dir():
        print(f"Verzeichnis nicht gefunden: {root}", file=sys.stderr)
        return 2
    errors = validate_catalog(root)
    for line in errors:
        print(line, file=sys.stderr)
    if errors:
        return 1
    print("Regelkatalog gültig")
    return 0


if __name__ == "__main__":
    sys.exit(main())

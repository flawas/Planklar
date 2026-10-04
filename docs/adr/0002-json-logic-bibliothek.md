# ADR 0002: JSON-Logic-Bibliothek `json-logic-qubit`

Status: akzeptiert

## Kontext

Der Plan sieht `json-logic-py` für `when`-Bedingungen vor. Das PyPI-Paket `json-logic`
(nadirizr/json-logic-py) läuft nur unter Python 2 (`tests.keys()[0]`); `json-logic-py` existiert
auf PyPI nicht.

## Entscheidung

`json-logic-qubit` (Python-3-Fork derselben Bibliothek, gleiche API `jsonLogic(logic, data)`).

## Folgen

- Abhängigkeit in `pyproject.toml`, mypy-Override wegen fehlender Typen.
- Fehlende Variablen erkennt `app/rules/applicability.py` selbst, da die Bibliothek sie als `None` auswertet.

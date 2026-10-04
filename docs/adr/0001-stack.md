# 0001 – Stack

## Kontext
Liquet prüft Baugesuche auf formale Vollständigkeit. Ein Einzelentwickler pflegt eine Codebasis; PDF-, OCR- und KI-Anbindung sind in Python am ausgereiftesten. Details: Implementationsplan, Abschnitt "Tech-Stack".

## Entscheidung
- Python 3.12, FastAPI, Jinja2 + HTMX (ein Service für API und UI, kein JS-Build)
- Celery mit Redis für Prüfläufe; PostgreSQL 16 (JSONB); MinIO (S3-kompatibel; seit ADR 0003 SeaweedFS)
- PyMuPDF, Tesseract (deu) als OCR-Fallback
- LiteLLM mit Vision-Modell und strukturiertem JSON-Output
- Eigene Regelengine mit JSON Logic (json-logic-py); Regelkatalog als YAML mit JSON-Schema
- WeasyPrint für Berichte; FastAPI-Users (OIDC vorbereitet); Caddy; Alembic, pytest
- Tooling: `pyproject.toml`, ruff (Lint + Format), pytest, mypy für `app/rules` und `app/pipeline`

## Konsequenzen
- Abhängigkeiten werden erst mit dem jeweiligen Issue ergänzt, nicht auf Vorrat.
- Abweichungen vom Stack brauchen ein neues ADR.
- Die KI beantwortet nur Einzelfragen; `erfüllt/fehlt` entscheidet allein `app/rules`.

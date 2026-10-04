# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Planklar is a pre-submission check for Swiss building permit applications (Baugesuche). It validates forms, plans, and attachments for completeness against cantonal and communal requirements before submission. Initial scope covers the cantons of Luzern and Schwyz.

The authoritative design is `Implementationsplan Baugesuch-Check.md` (scope, stack, data model, pipeline, tests, privacy). Follow it; deviations need an ADR in `docs/adr/`.

## Status

Das Gerüst steht (Issue #1); weitere Module entstehen über die Agent-Pipeline. Stack-Entscheidung: `docs/adr/0001-stack.md`.

## Befehle

```
pip install -e ".[dev]"          # Python 3.12
ruff check .                     # Lint
ruff format --check .            # Format (ohne --check: formatieren)
mypy                             # app/rules und app/pipeline
pytest                           # Tests (tests/ spiegelt app/)
uvicorn app.main:app --reload    # lokal starten, GET /health
celery -A app.worker worker --concurrency=2   # Worker (Broker: REDIS_URL)
```

`python -m app.rules.validate` validiert den Regelkatalog (`rules/`).
`python -m eval.run --model <name>` lässt das Evaluations-Harness laufen (manuell/wöchentlich, nie im PR-CI; Set in `eval/data/`).
Noch nicht vorhanden: `docker compose up -d`.

## Architektur

Zielstruktur und Abhängigkeitsrichtung (`web -> dossiers/reports -> rules/pipeline -> db`) stehen in `.claude/agents/architect.md`. Konfiguration nur über Umgebungsvariablen (`app/config.py`).

## Domain rules (apply to every agent and every change)

- Formal completeness only. No substantive building-law checks (distances, utilisation, zoning). The tool gives hints and decides nothing.
- The AI answers narrow single questions; only the rule engine (`app/rules`) decides `erfüllt / fehlt / unsicher / manuell`. When in doubt, never `erfüllt`.
- Every rule has a verifiable source (Erlass, Paragraph, URL) and `stand`. Never invent rules.
- No document contents or personal data in logs. Only whole pages/tiles go to the model, never whole dossiers.
- Tenant isolation per Büro on every data access.
- Never commit real building applications. Synthetic fixtures only.
- UI language German (Swiss spelling).

## Agent pipeline

Roles live in `.claude/agents/`: `product-owner`, `architect`, `backend`, `pipeline`, `rules`, `frontend`, `devops`, `qa`, `reviewer`. Each takes one kind of developer task.

Flow (GitHub Actions in `.github/workflows/`):

1. `agent-planner.yml` (manual) – product-owner turns the plan into issues with `agent:<role>`, `phase:<n>`, `status:ready|blocked` and `Depends on: #N`.
2. `agent-dev.yml` – label `status:ready` starts the matching role; it opens a PR from `agent/<role>/issue-<n>` with `Closes #<n>`.
3. `agent-review.yml` – reviewer comments and sets `review:approved` or `review:changes-requested`; the dev role fixes (max 3 rounds, commits prefixed `fix(review):`, then `needs-human`). 
4. `agent-merge.yml` – squash-merges an `agent/*` PR to main once it has `review:approved` (valid for the latest commit only), no conflicts and the CI workflow is green (`.github/scripts/merge-if-ready.sh`). Kill switch: repo variable `AUTO_MERGE=false`. Conflicts or red CI set `needs-human`.
5. `agent-orchestrator.yml` – on merge, `.github/scripts/unblock.sh` flips `status:blocked` to `status:ready` for issues whose dependencies are closed.
6. `ci.yml` – lint, tests, rule validation, docker build (each job activates once its files exist).

Required secrets (GitHub repository secrets): `AGENT_PAT` (GitHub PAT or App token) and `CLAUDE_CODE_OAUTH_TOKEN`. They are read directly from GitHub secrets, not from 1Password (the 1Password API rate-limited the many agent jobs). Use a PAT/App token rather than `GITHUB_TOKEN` because events created with the default `GITHUB_TOKEN` do not trigger other workflows, so the chain would stop. Run `.github/scripts/setup-labels.sh` once. Use branch protection on `main` requiring CI.

## Datenzugriff (Mandantentrennung)

Dossier, Dokument und Seite werden ausschliesslich über `app.dossiers.scope.BueroScope` gelesen und geschrieben (in Endpunkten via `Depends(get_scope)`). Direkte `select(Dossier)`/`session.get(Dokument, …)` ausserhalb dieser Schicht sind nicht erlaubt. Fremde Objekte lösen `NotFoundError` aus, Endpunkte antworten mit `not_found()` (404). Neue Entitäten (z. B. Prüflauf, Befund) werden in `BueroScope` ergänzt, jeweils mit einem Eintrag im Fremdzugriff-Test `tests/dossiers/test_scope.py`.

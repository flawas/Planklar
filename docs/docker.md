# Docker: Build und Start

Voraussetzung: Docker mit Compose v2.

## 1. Image bauen und Stack starten

```
docker compose up -d --build --wait
```

Das eine Image `liquet:dev` dient für `web` und `worker`. Dazu starten `db` (Postgres), `redis` und `s3` (SeaweedFS).
`web` führt vor dem Start `alembic upgrade head` aus. Nur das Image bauen: `docker compose build`.

Prüfen: <http://localhost:8000/health>

## 2. Standard-Login anlegen (einmalig beim Setup)

```
docker compose exec web python -m app.auth.seed --dev
```

Legt das Büro «Liquet» und den Admin an (idempotent, mehrfaches Ausführen ist unschädlich):

| E-Mail            | Passwort   |
|-------------------|------------|
| admin@liquet.ch   | `password` |

> Nur für die lokale Entwicklung. Auf Servern stattdessen eigenes Büro und Passwort setzen:
> `docker compose exec -e SEED_PASSWORD='…' web python -m app.auth.seed "<Büro>" "<E-Mail>"`

## Nützliche Befehle

```
docker compose logs -f web worker   # Logs
docker compose down                 # stoppen (Daten bleiben)
docker compose down -v              # stoppen und Daten löschen
```

Bei langsamer Leitung bricht der Build evtl. bei grossen Paketen ab: einfach erneut starten, der Pip-Cache bleibt erhalten.

## Fehlerbehebung

**`429 Too Many Requests … too many failed login attempts` beim Build**
Docker Hub sperrt vorübergehend, meist wegen fehlgeschlagener Logins (veraltete Zugangsdaten). Abhilfe:

```
docker logout
docker login        # mit gültigem Docker-Hub-Konto (Access Token), oder anonym nach einigen Minuten erneut versuchen
docker compose up -d --build --wait
```

Das Dockerfile lädt bewusst kein `docker/dockerfile:1`-Frontend nach (keine `# syntax`-Zeile); die Basis-Images `python`, `postgres`, `redis` kommen weiterhin von Docker Hub.

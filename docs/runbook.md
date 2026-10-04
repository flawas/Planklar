# Runbook

Betrieb des Compose-Stacks (`docker-compose.yml`). Alle Befehle im Projektverzeichnis.
Konfiguration über `.env` (Vorlage: `.env.example`), nie im Repo.

## Start

```
cp .env.example .env     # Werte anpassen: SITE_ADDRESS, AUTH_SECRET, AUTH_COOKIE_SECURE=true, BACKUP_DIR
docker compose up -d --build --wait
curl -fsS http://localhost:8080/health
```

`web` führt beim Start `alembic upgrade head` aus und lädt den Regelkatalog. Schlägt die Migration fehl, startet uvicorn nicht (`docker compose logs web`).

## Update

1. Backup erstellen (siehe unten).
2. `git pull` und ggf. Image-Tags in `docker-compose.yml` bewusst anheben.
3. `docker compose up -d --build --wait` (Migrationen laufen beim Start von `web`).
4. `curl -fsS http://localhost:8080/health`. Bei Fehlern: vorherigen Stand auschecken, neu bauen und bei Schemaänderungen das Backup einspielen.

## Backup

`scripts/backup.sh` erstellt
- einen Datenbank-Dump (`pg_dump -Fc`) in `$BACKUP_DIR/db/liquet-<Zeitstempel>.dump`,
- einen Spiegel des S3-Buckets in `$BACKUP_DIR/s3` (`aws s3 sync --delete`, über den Compose-Dienst `backup`).

`BACKUP_DIR` muss auf **separatem Speicher** liegen (eigenes Laufwerk, NFS-Mount oder ein Ziel, das ausserhalb des Hosts gesichert wird), sonst schützt das Backup nicht vor Plattenverlust. Dumps älter als `BACKUP_KEEP_DAYS` (Standard 14) werden gelöscht. Der Spiegel enthält Löschungen der Aufbewahrungsfrist (`RETENTION_DAYS`) ebenfalls; Dokumente verschwinden also auch aus dem Backup. `sync --delete` spiegelt aber auch versehentliche Löschungen oder einen leeren Bucket nach Volume-Verlust; deshalb den Backup-Speicher zusätzlich per Snapshot sichern.

Täglich per Cron (Beispiel, 02:30):

```
30 2 * * * cd /opt/liquet && set -a && . ./.env && set +a && scripts/backup.sh >>/var/log/liquet-backup.log 2>&1
```

Das Backup enthält Baugesuchsunterlagen und Personendaten: Zugriff auf `BACKUP_DIR` wie auf die Produktionsdaten beschränken. Das Skript setzt `umask 077` und `chmod 700` auf `BACKUP_DIR`.

## Restore

Überschreibt die vorhandenen Daten.

```
docker compose up -d --wait db s3        # Datenbank und Speicher müssen laufen
docker compose stop web worker           # keine Schreibzugriffe während der Wiederherstellung
scripts/restore.sh                       # neuester Dump; sonst: scripts/restore.sh <Dump-Datei>
docker compose up -d --wait
curl -fsS http://localhost:8080/health
```

Auf einem neuen Host: Repo auschecken, `.env` anlegen, `BACKUP_DIR` einhängen und die Schritte oben ausführen.
Den Restore regelmässig (mindestens quartalsweise) auf einem Testsystem prüfen: Dump einspielen, Anzahl Dossiers und ein Dokument vergleichen.

## Rotation von Secrets

Secrets stehen nur in `.env` bzw. als Docker Secrets auf dem Host, nie im Repo.

- **`AUTH_SECRET`**: neuen Wert erzeugen (`openssl rand -hex 32`), in `.env` setzen, `docker compose up -d web worker`. Bestehende Sitzungen werden ungültig, Nutzer melden sich neu an.
- **`LLM_API_KEY`**: beim Anbieter einen neuen Schlüssel erstellen, in `.env` setzen, `docker compose up -d web worker`, danach den alten Schlüssel beim Anbieter widerrufen.
- **Datenbank-Passwort**: `ALTER USER liquet PASSWORD '...'` in `db` ausführen, `DATABASE_URL` anpassen, `web` und `worker` neu starten.
- **S3-Zugangsdaten** (`S3_ACCESS_KEY`, `S3_SECRET_KEY`): im Speicher neues Schlüsselpaar anlegen, in `.env` setzen, `web`, `worker` neu starten, altes Paar entfernen.
- **GitHub-Secrets** (`AGENT_PAT`, `CLAUDE_CODE_OAUTH_TOKEN`): in den Repository-Einstellungen ersetzen und das alte Token widerrufen.

Nach jeder Rotation `curl -fsS .../health` prüfen und das nächste Backup kontrollieren.

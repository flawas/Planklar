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

## E-Mail-Versand (Einladung, Passwort-Reset)

Büro-Admins laden Benutzer per E-Mail ein (`POST /admin/einladungen`); der Passwort-Reset nutzt denselben Token-Mechanismus (`/auth/passwort-reset/anfordern`, `/einloesen`). Versand über SMTP, anbieterneutral, nur per Umgebungsvariablen:

- `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_STARTTLS` (`true`), `MAIL_FROM` (Absender) und `APP_BASE_URL` (Basis der Links in den Mails, z. B. `https://liquet.example.ch`).
- Ohne `SMTP_HOST` oder `MAIL_FROM` wird nicht versendet; das Log enthält `MAIL_FAILED` mit `code=MAIL_NOT_CONFIGURED`. Der Anbieter ist eine reine Konfigurationsentscheidung (#58/#59/#62).
- Tokens sind einmalig und nur als SHA-256-Hash gespeichert; Einladungen gelten 7 Tage, Reset-Links 2 Stunden. Weder Tokens noch Mailinhalte oder Adressen stehen im Log, nur Fehlercodes (`MAIL_SEND_FAILED`, `MAIL_NOT_CONFIGURED`).
- Die Tabellen `einladung` und `passwort_reset` haben bewusst kein RLS: Das Einlösen ist öffentlich und schlägt das Token vor dem Büro-Kontext nach.
- Tests verwenden `FakeMailer` (`app/mail.py`), nie echtes SMTP.

## Row-Level Security (Datenbankrollen)

Migration 0011 aktiviert RLS auf `dossier`, `dokument`, `seite`, `pruefung`, `befund` (mit `FORCE`) und legt die Rolle `liquet_app` an (NOBYPASSRLS, NOLOGIN). Superuser und Rollen mit `BYPASSRLS` umgehen RLS immer; die App darf deshalb nicht als `POSTGRES_USER` (Superuser) laufen.

1. `python -m app.db.app_role` setzt Login und Passwort (`DB_APP_PASSWORD`) der Rolle; der Compose-Start (`web`) ruft es nach den Migrationen auf.
2. Web, Worker und Beat verwenden diese Rolle in `DATABASE_URL`; `alembic upgrade head` und `app_role` laufen mit `MIGRATION_DATABASE_URL` (Besitzerrolle, Fallback `DATABASE_URL`).
3. `REQUIRE_RLS_ROLE=true` (in Compose gesetzt) bricht den Start ab, wenn die App-Rolle Superuser ist oder `BYPASSRLS` hat; sonst warnt das Log mit `DB_ROLE_BYPASSES_RLS`.
4. Jeder Pfad setzt den Büro-Kontext über `BueroScope` (`app/db/rls.py`). Ohne Kontext liefern Abfragen keine Zeilen, das ist beabsichtigt. Celery-Tasks erhalten `buero_id` als Argument; der Retention-Job setzt den Kontext je Büro.

## Büro-Offboarding (Vertragsende)

Löscht ein Büro unwiderruflich samt Dossiers (inkl. Dokumente, Seiten, Prüfläufe, Befunde), S3-Objekten (gesamtes Präfix `buero/<buero_id>/`, auch verwaiste Objekte), Einladungen und Benutzern (revDSG). Andere Büros bleiben unberührt.

1. Büro-ID ermitteln (z. B. im Plattform-Bereich oder `SELECT id, name FROM buero;`) und Vertragsende bzw. Auftrag schriftlich festhalten. Optional vorher ein Backup ziehen (siehe Backup); danach gelöschte Daten verbleiben dort bis zum Ablauf der Backup-Aufbewahrung.
2. Büro sperren (`aktiv=false`), damit niemand mehr arbeitet.
3. Ausführen im `web`-Container: `docker compose exec web python -m app.dossiers.offboarding <buero_id> --bestaetigen`. Ohne `--bestaetigen` passiert nichts (Exit 2).
4. Die Ausgabe nennt nur Anzahlen (Dossiers, Dokumente, Benutzer). Exit 0 = vollständig gelöscht. Bei Exit 1 mit "Fehlgeschlagen" (z. B. Speicher nicht erreichbar) bleibt das Büro bestehen: Ursache beheben und das Kommando erneut ausführen (idempotent).
5. Enthält das Büro einen Plattform-Admin, bricht das Kommando ab; diesen Benutzer zuvor in ein anderes Büro verschieben bzw. entfernen.
6. Kontrolle: `SELECT count(*) FROM buero WHERE id = '<buero_id>';` ergibt 0; im Bucket ist das Präfix `buero/<buero_id>/` leer.

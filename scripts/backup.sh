#!/usr/bin/env bash
# Tägliches Backup: pg_dump der Datenbank und Spiegel des S3-Buckets nach $BACKUP_DIR.
# BACKUP_DIR gehört auf separaten Speicher (anderes Laufwerk/Mount), nicht ins Repo.
# Aufruf im Projektverzeichnis: scripts/backup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
POSTGRES_USER="${POSTGRES_USER:-liquet}"
POSTGRES_DB="${POSTGRES_DB:-liquet}"
export BACKUP_DIR

# Dumps und Spiegel enthalten Personendaten: nur für den ausführenden Benutzer lesbar.
umask 077
mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/s3"
chmod 700 "$BACKUP_DIR" "$BACKUP_DIR/db" "$BACKUP_DIR/s3"
stamp="$(date +%Y%m%d-%H%M%S)"
target="$BACKUP_DIR/db/liquet-$stamp.dump"

# Zuerst in eine Teildatei schreiben, damit ein abgebrochener Dump nie als Backup gilt.
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" >"$target.part"
mv "$target.part" "$target"

# Spiegel inkl. Löschungen: nach Aufbewahrungsfrist gelöschte Dokumente verschwinden auch im Backup.
docker compose --profile backup run --rm backup \
	s3 sync "s3://${S3_BUCKET:-liquet}" /backup/s3 --delete --only-show-errors

find "$BACKUP_DIR/db" -name 'liquet-*.dump' -mtime "+$BACKUP_KEEP_DAYS" -delete
echo "Backup fertig: $target"

#!/usr/bin/env bash
# Stellt Datenbank und S3-Bucket aus $BACKUP_DIR wieder her. Überschreibt vorhandene Daten.
# Aufruf: scripts/restore.sh [Dump-Datei]   (Standard: neuester Dump in $BACKUP_DIR/db)
set -euo pipefail

cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-./backups}"
POSTGRES_USER="${POSTGRES_USER:-liquet}"
POSTGRES_DB="${POSTGRES_DB:-liquet}"
export BACKUP_DIR
umask 077

dump="${1:-$(ls -1 "$BACKUP_DIR"/db/liquet-*.dump 2>/dev/null | sort | tail -n 1 || true)}"
if [ -z "$dump" ] || [ ! -f "$dump" ]; then
	echo "Kein Dump gefunden (Argument oder $BACKUP_DIR/db/liquet-*.dump)" >&2
	exit 1
fi

echo "Stelle Datenbank aus $dump wieder her"
docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
	--clean --if-exists --no-owner <"$dump"

if [ -d "$BACKUP_DIR/s3" ]; then
	echo "Stelle S3-Bucket aus $BACKUP_DIR/s3 wieder her"
	docker compose --profile backup run --rm backup \
		s3 sync /backup/s3 "s3://${S3_BUCKET:-liquet}" --only-show-errors
fi
echo "Wiederherstellung fertig"

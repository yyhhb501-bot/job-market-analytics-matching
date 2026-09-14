#!/usr/bin/env bash
# Backup the production PostgreSQL database to a compressed SQL dump and prune
# old copies. Safe to run from cron on the Docker host:
#
#   15 2 * * * /opt/jobseek/scripts/backup_postgres.sh >> /var/log/jobseek-backup.log 2>&1
#
# Restore with:
#   gunzip -c backups/jobs-YYYYmmdd-HHMMSS.sql.gz | \
#     docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB"
set -euo pipefail

PG_CONTAINER="${PG_CONTAINER:-jobseek-postgres-1}"
PG_USER="${PG_USER:-jobuser}"
PG_DB="${PG_DB:-jobs}"
BACKUP_DIR="${BACKUP_DIR:-$(cd "$(dirname "$0")/.." && pwd)/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
timestamp="$(date +%Y%m%d-%H%M%S)"
target="$BACKUP_DIR/${PG_DB}-${timestamp}.sql.gz"

echo "[backup] dumping $PG_DB from $PG_CONTAINER -> $target"
if ! docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" \
    --no-owner --clean --if-exists | gzip -9 > "$target"; then
    echo "[backup] FAILED" >&2
    rm -f "$target"
    exit 1
fi

# Guard against silently-empty dumps.
if [ ! -s "$target" ] || [ "$(wc -c < "$target")" -lt 1024 ]; then
    echo "[backup] dump looks empty; refusing to keep it" >&2
    rm -f "$target"
    exit 1
fi

echo "[backup] ok: $(du -h "$target" | cut -f1)"

echo "[backup] pruning dumps older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -name "${PG_DB}-*.sql.gz" -type f -mtime "+${RETENTION_DAYS}" -print -delete

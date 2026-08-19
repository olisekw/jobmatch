#!/usr/bin/env bash
# Nightly backup: a compressed pg_dump plus the CVs, kept for $KEEP_DAYS and
# mirrored off the box.
#
# Install on the VPS as a root cron entry (`crontab -e`):
#
#   17 3 * * *  /opt/jobmatch/deploy/backup.sh >> /var/log/jobmatch-backup.log 2>&1
#
# The dump is taken with `docker compose exec` rather than a published port, so
# Postgres stays unreachable from outside the compose network.
#
# Restoring is `deploy/restore-check.sh`, which is also how you find out whether
# any of this works. Run it. A backup that has never been restored is not a
# backup — that sentence is a roadmap checkpoint, not a slogan.

set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/opt/jobmatch}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/jobmatch}"
KEEP_DAYS="${KEEP_DAYS:-14}"
# rsync/scp target for the off-box copy, e.g. a Hetzner Storage Box:
#   REMOTE_TARGET=u123456@u123456.your-storagebox.de:jobmatch/
# Empty means local-only, which is not a backup if the box is what dies.
REMOTE_TARGET="${REMOTE_TARGET:-}"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
cd "$COMPOSE_DIR"

dump="$BACKUP_DIR/jobmatch-$stamp.sql.gz"
cvs="$BACKUP_DIR/resumes-$stamp.tar.gz"

echo "[$(date -u +%FT%TZ)] dumping database → $dump"
# --clean --if-exists so the dump can be replayed over a non-empty database;
# no --owner, since the restore target may use a different role.
docker compose exec -T db \
	pg_dump --username=jobmatch --dbname=jobmatch --clean --if-exists --no-owner \
	| gzip -9 > "$dump.partial"
mv "$dump.partial" "$dump"

echo "[$(date -u +%FT%TZ)] archiving CVs → $cvs"
# The CVs are the other half of the user's data and live in a docker volume,
# not in Postgres. `web` mounts it at /app/data.
docker compose exec -T web tar -cz -C /app/data resumes > "$cvs.partial"
mv "$cvs.partial" "$cvs"

# Gzip stores a CRC; this catches a dump truncated by a full disk, which is the
# realistic failure and the one that looks fine until the day you need it.
gzip -t "$dump"
gzip -t "$cvs"

if [ -n "$REMOTE_TARGET" ]; then
	echo "[$(date -u +%FT%TZ)] copying to $REMOTE_TARGET"
	rsync --archive --compress --partial "$dump" "$cvs" "$REMOTE_TARGET"
else
	echo "WARNING: REMOTE_TARGET is unset — these backups only exist on this box."
fi

echo "[$(date -u +%FT%TZ)] pruning local copies older than $KEEP_DAYS days"
find "$BACKUP_DIR" -name 'jobmatch-*.sql.gz' -mtime "+$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'resumes-*.tar.gz' -mtime "+$KEEP_DAYS" -delete

echo "[$(date -u +%FT%TZ)] done — $(du -h "$dump" | cut -f1) database, $(du -h "$cvs" | cut -f1) CVs"

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
# backup — that sentence is a roadmap checkpoint, not a slogan. Run it against a
# dump `deploy/backup-pull.sh` fetched back from the remote, not against the
# local copy: the local copy proves pg_dump works, the pulled one proves the
# backup survives the box.

set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/opt/jobmatch}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/jobmatch}"
KEEP_DAYS="${KEEP_DAYS:-14}"
# Where the off-box copy goes. Empty means local-only, which is not a backup if
# the box is what dies.
#
#   REMOTE_TOOL=rsync   an ssh target:     u123456@u123456.your-storagebox.de:jobmatch/
#   REMOTE_TOOL=rclone  an object store:   oracle:jobmatch/  (or b2:, r2:, …)
#
# The free path is an object store, not a box: Oracle reclaims an Always Free
# *compute* instance that idles under 20% for 7 days, and a machine whose only
# job is to receive a 5 MB dump at 03:17 is idle by definition — so a second VM
# is the one target that gets deleted for working correctly. Buckets are not
# subject to that rule. Object stores do not speak rsync, which is why the
# transport is a choice here rather than a hardcoded `rsync`.
REMOTE_TARGET="${REMOTE_TARGET:-}"
REMOTE_TOOL="${REMOTE_TOOL:-rsync}"
# The remote is finite on a free tier, and nothing used to prune it: only the
# local copies were ever deleted, so the bucket grew forever.
REMOTE_KEEP_DAYS="${REMOTE_KEEP_DAYS:-$KEEP_DAYS}"

# Checked before the dump, not after it: a typo in REMOTE_TOOL should cost a
# second, not a full pg_dump and a tar of every CV first.
case "$REMOTE_TOOL" in
rsync | rclone) ;;
*)
	echo "ERROR: REMOTE_TOOL must be 'rsync' or 'rclone', not '$REMOTE_TOOL'." >&2
	exit 2
	;;
esac

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
	echo "[$(date -u +%FT%TZ)] copying to $REMOTE_TARGET via $REMOTE_TOOL"
	case "$REMOTE_TOOL" in
	rsync)
		rsync --archive --compress --partial "$dump" "$cvs" "$REMOTE_TARGET"
		# No remote prune here: pruning over rsync means running `find` on the
		# far end, and an ssh target that only offers rsync/sftp has no shell to
		# run it in. `--delete` would do it, but a mistyped target would then
		# delete rather than merely misplace. Prune that target its own way.
		;;
	rclone)
		# Every name carries its own UTC stamp, so a name that already exists
		# means two runs in one second or a clock that stepped backwards —
		# never something to resolve by replacing a good backup with a new one.
		#
		# This is an explicit check and not `--immutable`, which documents
		# exactly this behaviour and does not deliver it: measured on rclone
		# v1.75.1, `copy --immutable` over an existing object of a different
		# size logged "Copied (replaced existing)" and exited 0, replacing a
		# 5.7 MB dump with a 391-byte file. A guard that cannot fire is worse
		# than none, because it is the one you stop checking.
		#
		# Racy in principle — the listing and the copy are not one operation —
		# but the race needs two backups in the same second, and the check it
		# replaces did not work at all.
		# `|| true` because the very first run has nothing to list: rclone exits
		# 3 with "directory not found" on a prefix that does not exist yet, and
		# under `set -e` that turned the first-ever backup into a failure that
		# copied nothing. A listing that fails means "nothing there to clash
		# with"; a remote that is genuinely unreachable still fails below, on
		# the copy, which is the operation that has to work.
		existing="$(rclone lsf "$REMOTE_TARGET" 2>/dev/null || true)"
		for f in "$dump" "$cvs"; do
			if printf '%s\n' "$existing" | grep -Fxq "$(basename "$f")"; then
				echo "ERROR: $(basename "$f") already exists at $REMOTE_TARGET — refusing to replace it." >&2
				exit 1
			fi
		done
		rclone copy "$dump" "$REMOTE_TARGET"
		rclone copy "$cvs" "$REMOTE_TARGET"

		echo "[$(date -u +%FT%TZ)] pruning remote copies older than $REMOTE_KEEP_DAYS days"
		rclone delete --min-age "${REMOTE_KEEP_DAYS}d" \
			--include 'jobmatch-*.sql.gz' --include 'resumes-*.tar.gz' \
			"$REMOTE_TARGET"
		;;
	esac
else
	echo "WARNING: REMOTE_TARGET is unset — these backups only exist on this box."
fi

echo "[$(date -u +%FT%TZ)] pruning local copies older than $KEEP_DAYS days"
find "$BACKUP_DIR" -name 'jobmatch-*.sql.gz' -mtime "+$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'resumes-*.tar.gz' -mtime "+$KEEP_DAYS" -delete

echo "[$(date -u +%FT%TZ)] done — $(du -h "$dump" | cut -f1) database, $(du -h "$cvs" | cut -f1) CVs"

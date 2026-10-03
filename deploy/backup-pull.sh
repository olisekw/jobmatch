#!/usr/bin/env bash
# Fetch a backup back from the remote, so it can be restored.
#
#   deploy/backup-pull.sh --latest
#   deploy/backup-pull.sh 20260913T031700Z
#
# Then: deploy/restore-check.sh <the path this prints>
#
# This exists because `backup.sh` only ever pushed. The roadmap's verification
# for backups is a restore from a dump *pulled back from the remote*, and there
# was no way to pull one — so the only thing ever restored was the local copy,
# which proves `pg_dump` works and proves nothing at all about whether the
# off-box copy is real, intact, or even there.
#
# It pulls into its own directory rather than $BACKUP_DIR on purpose: dropping
# the remote copy on top of the local one would make the two indistinguishable,
# and a round trip you cannot tell from a local read is not a round trip.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/jobmatch}"
PULL_DIR="${PULL_DIR:-$BACKUP_DIR/pulled}"
REMOTE_TARGET="${REMOTE_TARGET:-}"
REMOTE_TOOL="${REMOTE_TOOL:-rsync}"

want="${1:-}"
if [ -z "$want" ]; then
	echo "usage: $0 <--latest|STAMP>" >&2
	exit 2
fi
if [ -z "$REMOTE_TARGET" ]; then
	echo "ERROR: REMOTE_TARGET is unset — there is no remote to pull from." >&2
	exit 2
fi
if [ "$REMOTE_TOOL" != "rclone" ]; then
	# rsync targets vary too much to guess at (shell or no shell, sftp-only,
	# BusyBox `ls`). Saying so is better than shipping a listing that works on
	# one vendor and silently returns nothing on the next.
	echo "ERROR: --latest and remote listing need REMOTE_TOOL=rclone." >&2
	echo "For an rsync target, copy the file back by hand:" >&2
	echo "  rsync -v ${REMOTE_TARGET%/}/jobmatch-<stamp>.sql.gz $PULL_DIR/" >&2
	exit 2
fi

mkdir -p "$PULL_DIR"

if [ "$want" = "--latest" ]; then
	# Names are UTC stamps in a fixed width, so lexical order is chronological.
	name="$(rclone lsf --include 'jobmatch-*.sql.gz' "$REMOTE_TARGET" | sort | tail -n 1)"
	if [ -z "$name" ]; then
		echo "ERROR: no jobmatch-*.sql.gz found at $REMOTE_TARGET." >&2
		exit 1
	fi
else
	name="jobmatch-$want.sql.gz"
fi

echo "pulling $name from $REMOTE_TARGET"
rclone copy "$REMOTE_TARGET/$name" "$PULL_DIR"

pulled="$PULL_DIR/$name"
if [ ! -f "$pulled" ]; then
	echo "ERROR: $name did not arrive in $PULL_DIR." >&2
	exit 1
fi

# The same CRC check backup.sh runs before pushing. Running it again after the
# pull is the point: it is the round trip, not the dump, that is under test.
gzip -t "$pulled"

echo "pulled OK — $(du -h "$pulled" | cut -f1)"
echo "$pulled"

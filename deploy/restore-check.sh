#!/usr/bin/env bash
# Restore a backup into a throwaway database and diff the row counts against
# the live one. This is the Phase 5 verification checkpoint, written down:
#
#   deploy/restore-check.sh /var/backups/jobmatch/jobmatch-20260813T031700Z.sql.gz
#
# Nothing here touches the live database. The scratch database is created and
# dropped inside the same Postgres container, which is also what makes this
# honest: it exercises the actual dump, not a copy of the live volume.

set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/opt/jobmatch}"
SCRATCH_DB="${SCRATCH_DB:-jobmatch_restore_check}"

dump="${1:-}"
if [ -z "$dump" ] || [ ! -f "$dump" ]; then
	echo "usage: $0 <jobmatch-*.sql.gz>" >&2
	exit 2
fi

cd "$COMPOSE_DIR"

psql_scratch() { docker compose exec -T db psql -qtAX --username=jobmatch --dbname="$SCRATCH_DB" "$@"; }
psql_live()    { docker compose exec -T db psql -qtAX --username=jobmatch --dbname=jobmatch "$@"; }

cleanup() {
	docker compose exec -T db dropdb --username=jobmatch --if-exists "$SCRATCH_DB" || true
}
trap cleanup EXIT

echo "creating scratch database $SCRATCH_DB"
docker compose exec -T db dropdb --username=jobmatch --if-exists "$SCRATCH_DB"
docker compose exec -T db createdb --username=jobmatch "$SCRATCH_DB"

echo "restoring $dump"
# ON_ERROR_STOP so a failed restore fails this script instead of leaving a
# half-populated database that then "matches" on the tables that made it.
gunzip -c "$dump" | docker compose exec -T db \
	psql --username=jobmatch --dbname="$SCRATCH_DB" --quiet --set ON_ERROR_STOP=on \
	> /dev/null

echo
printf '%-22s %10s %10s\n' table live restored
status=0
for table in users jobs user_jobs user_settings applications application_events scans; do
	live="$(psql_live -c "SELECT COUNT(*) FROM $table" | tr -d '[:space:]')"
	restored="$(psql_scratch -c "SELECT COUNT(*) FROM $table" | tr -d '[:space:]')"
	flag=""
	if [ "$live" != "$restored" ]; then
		flag="  ← MISMATCH"
		status=1
	fi
	printf '%-22s %10s %10s%s\n' "$table" "$live" "$restored" "$flag"
done

# Row counts alone would pass on a dump full of NULLs. The score sum is the
# number every earlier checkpoint tracked, so it is the one to carry forward.
echo
live_sum="$(psql_live -c 'SELECT COALESCE(SUM(match_score), 0) FROM user_jobs' | tr -d '[:space:]')"
restored_sum="$(psql_scratch -c 'SELECT COALESCE(SUM(match_score), 0) FROM user_jobs' | tr -d '[:space:]')"
printf '%-22s %10s %10s' 'sum(match_score)' "$live_sum" "$restored_sum"
if [ "$live_sum" != "$restored_sum" ]; then
	printf '  ← MISMATCH'
	status=1
fi
echo

echo
if [ "$status" -eq 0 ]; then
	echo "RESTORE OK — the dump reproduces the live database."
else
	echo "RESTORE MISMATCH — do not trust this backup." >&2
fi
exit "$status"

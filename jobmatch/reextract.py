"""Re-run the insert-time derivations over jobs already in the database — safe
to re-run.

Extraction and placement both happen once, at insert time, so a fix to the
`config.py` patterns or to the `places` tables only reaches jobs scanned
*after* it. This replays `extract.extract_all` over every stored description
and `places.codes` over every stored location, so existing rows get the
benefit too, then re-scores.

Two rules keep it honest:

- **A source's structured fields still win.** Each adapter declares what it
  supplies in `JobSource.provides`; those columns are never overwritten here,
  because in the DB a board-supplied "remote" is indistinguishable from a
  regex-derived one. Only fields the board left to regex are recomputed.
- **Nothing user-owned is touched** — statuses, applications and events are
  untouched; `match_score` changes only because its inputs did. Everything it
  writes is derived from columns the row already carries.

Dry run by default; pass --apply to write.

Usage: python3 -m jobmatch.reextract [--apply]
"""

import sys
from collections import Counter

from . import db, extract, places, scoring
from .sources import SOURCES

# Columns this tool can recompute, mapped to their `extract_all` key.
FIELDS = ("skills", "worktype", "seniority", "employment_type")


def _status_counts(conn):
    """Per-user triage counts — the guard that nothing user-owned moved."""
    return {
        (row["user_id"], row["status"]): row["n"]
        for row in conn.execute(
            "SELECT user_id, status, COUNT(*) AS n FROM user_jobs GROUP BY user_id, status"
        )
    }


def _recompute(conn):
    """Return (updates, changes) without writing anything.

    `updates` is a list of (skills, worktype, seniority, employment_type, id)
    for rows that actually differ; `changes` counts transitions per field.
    """
    rows = conn.execute(
        "SELECT id, source, description, skills, worktype, seniority, employment_type "
        "FROM jobs WHERE TRIM(COALESCE(description, '')) != ''"
    ).fetchall()

    updates, changes = [], {field: Counter() for field in FIELDS}
    unknown_sources = Counter()

    for row in rows:
        source = SOURCES.get(row["source"])
        if source is None:
            # A board that's no longer registered: we can't know what it
            # supplied, so leave its structured fields alone.
            unknown_sources[row["source"]] += 1
            provides = set(FIELDS)
        else:
            provides = set(source.provides)

        features = extract.extract_all(row["description"])
        new = {}
        for field in FIELDS:
            # `skills` is always regex-derived — no adapter supplies it.
            keep = field in provides and field != "skills"
            new[field] = row[field] if keep else features[field]

        if any(new[field] != row[field] for field in FIELDS):
            for field in FIELDS:
                if new[field] != row[field]:
                    changes[field][(row[field], new[field])] += 1
            updates.append(dict(new, id=row["id"]))

    if unknown_sources:
        print(f"  note: unregistered sources left untouched: {dict(unknown_sources)}")
    print(f"scanned {len(rows)} jobs with descriptions; {len(updates)} would change")
    return updates, changes


def _replace_places(conn):
    """Return the `country`/`countries` rows a re-derivation would change.

    `places` is the same shape as `extract`: a derivation run once at insert
    time, so a fix to its tables — a town added, or the multi-region rule that
    stopped "LATAM, Europe, USA, Canada, APAC" being stored as `US` — only
    reaches rows scanned after it. Both columns are recomputed together
    because they are one derivation, and neither is user-owned.

    A row nothing places any more keeps what it has: an emptier answer is not
    a better one, and `SOURCE_DEFAULT` already covers the boards that can be
    guessed for.
    """
    rows = conn.execute(
        "SELECT id, source, location, country, countries FROM jobs"
    ).fetchall()

    updates, moved = [], Counter()
    for row in rows:
        found = places.codes(row["source"], row["location"])
        if not found:
            continue
        primary, packed = places.primary(found), places.pack(found)
        if primary == row["country"] and packed == row["countries"]:
            continue
        moved[(row["country"], primary)] += 1
        updates.append({"country": primary, "countries": packed, "id": row["id"]})

    print(f"scanned {len(rows)} jobs for placement; {len(updates)} would change")
    if moved:
        top = ", ".join(f"{old or '—'}→{new or '—'}: {n}"
                        for (old, new), n in moved.most_common(8))
        print(f"  country: {top}")
    return updates


def _report(changes):
    for field in FIELDS:
        counter = changes[field]
        if not counter:
            continue
        if field == "skills":
            print(f"  {field}: {sum(counter.values())} rows re-extracted")
            continue
        top = ", ".join(f"{old or '—'}→{new or '—'}: {n}"
                        for (old, new), n in counter.most_common(8))
        print(f"  {field}: {top}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    apply = "--apply" in argv

    conn = db.get_conn()
    before = _status_counts(conn)

    updates, changes = _recompute(conn)
    _report(changes)
    placements = _replace_places(conn)

    if not apply:
        print("\ndry run — nothing written. Re-run with --apply to commit.")
        conn.close()
        return

    conn.executemany(
        "UPDATE jobs SET skills = :skills, worktype = :worktype, "
        "seniority = :seniority, employment_type = :employment_type WHERE id = :id",
        updates,
    )
    conn.executemany(
        "UPDATE jobs SET country = :country, countries = :countries WHERE id = :id",
        placements,
    )
    conn.commit()
    print(f"\napplied {len(updates)} extraction and {len(placements)} placement updates")

    after = _status_counts(conn)
    assert before == after, f"status counts changed! {before} → {after}"
    print(f"status counts unchanged: {after}")

    print(f"rescored {scoring.rescore_all_users(conn)} user/job rows")
    conn.close()


if __name__ == "__main__":
    main()

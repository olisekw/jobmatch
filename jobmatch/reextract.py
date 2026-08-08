"""Re-run regex extraction over jobs already in the database — safe to re-run.

Extraction happens once, at insert time, so a fix to the `config.py` patterns
only reaches jobs scanned *after* it. This replays `extract.extract_all` over
every stored description so existing rows get the benefit too, then re-scores.

Two rules keep it honest:

- **A source's structured fields still win.** Each adapter declares what it
  supplies in `JobSource.provides`; those columns are never overwritten here,
  because in the DB a board-supplied "remote" is indistinguishable from a
  regex-derived one. Only fields the board left to regex are recomputed.
- **Nothing user-owned is touched** — statuses, applications and events are
  untouched; `match_score` changes only because its inputs did.

Dry run by default; pass --apply to write.

Usage: python3 -m jobmatch.reextract [--apply]
"""

import sys
from collections import Counter

from . import db, extract, scoring
from .sources import SOURCES

# Columns this tool can recompute, mapped to their `extract_all` key.
FIELDS = ("skills", "worktype", "seniority", "employment_type")


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
            updates.append(tuple(new[field] for field in FIELDS) + (row["id"],))

    if unknown_sources:
        print(f"  note: unregistered sources left untouched: {dict(unknown_sources)}")
    print(f"scanned {len(rows)} jobs with descriptions; {len(updates)} would change")
    return updates, changes


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
    before = {
        row["status"]: row["n"]
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
    }

    updates, changes = _recompute(conn)
    _report(changes)

    if not apply:
        print("\ndry run — nothing written. Re-run with --apply to commit.")
        conn.close()
        return

    conn.executemany(
        "UPDATE jobs SET skills = ?, worktype = ?, seniority = ?, employment_type = ? "
        "WHERE id = ?",
        updates,
    )
    conn.commit()
    print(f"\napplied {len(updates)} row updates")

    after = {
        row["status"]: row["n"]
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
    }
    assert before == after, f"status counts changed! {before} → {after}"
    print(f"status counts unchanged: {after}")

    print(f"rescored {scoring.rescore_all(conn)} jobs")
    conn.close()


if __name__ == "__main__":
    main()

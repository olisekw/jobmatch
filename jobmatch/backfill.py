"""Backfill new columns on a live database — safe to re-run.

Only fills NULLs: posted_at (from freshness + scraped_at) and the structured
salary columns (from the salary string). Also swaps robimeit out of
enabled_sources for the new international boards. Never touches statuses,
scores, applications or any user-edited value.

Usage: python3 -m jobmatch.backfill
"""

from . import dates, db, salary
from .sources import SOURCES


def backfill_posted(conn):
    rows = conn.execute(
        "SELECT id, freshness, scraped_at FROM jobs "
        "WHERE posted_at IS NULL AND freshness IS NOT NULL"
    ).fetchall()
    filled = 0
    for row in rows:
        posted = dates.parse_posted(row["freshness"], row["scraped_at"])
        if posted:
            conn.execute("UPDATE jobs SET posted_at = ? WHERE id = ?", (posted, row["id"]))
            filled += 1
    conn.commit()
    print(f"posted_at: {filled}/{len(rows)} rows filled")


def backfill_salary(conn):
    rows = conn.execute(
        "SELECT id, salary FROM jobs "
        "WHERE salary IS NOT NULL AND salary_min IS NULL AND salary_max IS NULL"
    ).fetchall()
    filled = 0
    for row in rows:
        s_min, s_max, s_cur, s_per = salary.parse_salary(row["salary"])
        if s_min is None and s_max is None:
            continue
        conn.execute(
            "UPDATE jobs SET salary_min = ?, salary_max = ?, "
            "salary_currency = ?, salary_period = ? WHERE id = ?",
            (s_min, s_max, s_cur, s_per, row["id"]),
        )
        filled += 1
    conn.commit()
    print(f"salary: {filled}/{len(rows)} rows parsed into structured columns")


def update_enabled_sources(conn):
    current = db.get_setting(conn, "enabled_sources") or []
    updated = [s for s in current if s in SOURCES]
    for name in SOURCES:
        if name not in updated:
            updated.append(name)
    if updated != current:
        db.set_setting(conn, "enabled_sources", updated)
    print(f"enabled_sources: {current} → {updated}")


def main():
    conn = db.get_conn()
    db.init_schema(conn)  # adds the new columns idempotently

    before = {
        row["status"]: row["n"]
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
    }

    backfill_posted(conn)
    backfill_salary(conn)
    update_enabled_sources(conn)

    after = {
        row["status"]: row["n"]
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
    }
    assert before == after, f"status counts changed! {before} → {after}"
    print(f"status counts unchanged: {after}")
    conn.close()


if __name__ == "__main__":
    main()

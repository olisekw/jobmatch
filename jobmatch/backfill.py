"""Backfill and migrate a live database — safe to re-run.

Two jobs in one command:

1. **Additive column backfill** (the original purpose): fill NULLs in posted_at
   and the structured salary columns, and keep enabled_sources in step with the
   registry. Never touches statuses, scores, applications or user-edited values.
2. **The one-time move to multi-tenancy**: create the local user, lift every
   per-user column out of the shared `jobs` table into `user_jobs`, copy
   `settings` into `user_settings`, stamp `applications`/`application_events`
   with a user_id, and move the CV to `data/resumes/<user_id>.pdf`.

Step 2 detects that it has already run and becomes a no-op, so this stays
idempotent. It is also **SQLite-only by design**: rewriting tables in place is a
migration of an existing local database, and a Phase 5 Postgres deployment
starts from `create_all` on an empty schema and never takes this path.

Back up first — `cp data/jobmatch.db data/jobmatch.db.bak` — then:

Usage: python3 -m jobmatch.backfill
"""

import shutil
import sqlite3

import sqlalchemy as sa
from sqlalchemy import MetaData
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.schema import CreateIndex, CreateTable

import config

from . import dates, db, salary
from .sources import SOURCES

_DIALECT = sqlite_dialect.dialect()


def backfill_posted(conn):
    rows = conn.execute(
        "SELECT id, freshness, scraped_at FROM jobs "
        "WHERE posted_at IS NULL AND freshness IS NOT NULL"
    ).fetchall()
    filled = 0
    for row in rows:
        posted = dates.parse_posted(row["freshness"], row["scraped_at"])
        if posted:
            conn.execute(
                "UPDATE jobs SET posted_at = :posted WHERE id = :id",
                {"posted": posted, "id": row["id"]},
            )
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
            "UPDATE jobs SET salary_min = :s_min, salary_max = :s_max, "
            "salary_currency = :s_cur, salary_period = :s_per WHERE id = :id",
            {"s_min": s_min, "s_max": s_max, "s_cur": s_cur,
             "s_per": s_per, "id": row["id"]},
        )
        filled += 1
    conn.commit()
    print(f"salary: {filled}/{len(rows)} rows parsed into structured columns")


def update_enabled_sources(conn, user_id):
    current = db.get_setting(conn, user_id, "enabled_sources") or []
    updated = [s for s in current if s in SOURCES]
    for name in SOURCES:
        if name not in updated:
            updated.append(name)
    if updated != current:
        db.set_setting(conn, user_id, "enabled_sources", updated)
    print(f"enabled_sources: {current} → {updated}")


# ── The one-time multi-tenant migration ──────────────────────

def _cursor_columns(cursor, table):
    """Column names, read through a raw sqlite3 cursor (the rebuild path)."""
    return {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}


def _cursor_has_table(cursor, table):
    return cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def needs_multiuser_migration(conn):
    """True while `jobs` still carries the per-user columns."""
    columns = sa.inspect(conn.sa).get_columns("jobs")
    return "status" in {column["name"] for column in columns}


def _status_counts(conn, sql, params=None):
    return {row["status"]: row["n"] for row in conn.execute(sql, params)}


def lift_per_user_data(conn, user_id):
    """Copy statuses, scores and settings out of the shared tables.

    The `WHERE true` in both statements is load-bearing, not decoration: after
    an INSERT … SELECT, SQLite cannot tell whether `ON` opens an upsert clause
    or a join, and refuses to parse it. A trailing WHERE resolves the ambiguity.
    Postgres accepts the same clause, so this stays one statement for Phase 5.
    """
    moved = conn.execute(
        """INSERT INTO user_jobs
               (user_id, job_id, status, match_score, score_breakdown, scored_at)
           SELECT :user_id, id, status, match_score, score_breakdown, scored_at
           FROM jobs
           WHERE true
           ON CONFLICT (user_id, job_id) DO NOTHING""",
        {"user_id": user_id},
    ).rowcount
    print(f"user_jobs: {moved} rows materialized for user {user_id}")

    if sa.inspect(conn.sa).has_table("settings"):
        copied = conn.execute(
            """INSERT INTO user_settings (user_id, key, value)
               SELECT :user_id, key, value FROM settings
               WHERE true
               ON CONFLICT (user_id, key) DO NOTHING""",
            {"user_id": user_id},
        ).rowcount
        print(f"user_settings: {copied} keys copied for user {user_id}")
    conn.commit()

    # The lift is only trustworthy if every triage decision survived it.
    before = _status_counts(conn, "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
    after = _status_counts(
        conn,
        "SELECT status, COUNT(*) AS n FROM user_jobs WHERE user_id = :user_id GROUP BY status",
        {"user_id": user_id},
    )
    assert before == after, f"status counts did not survive the lift! {before} → {after}"
    print(f"status counts carried over intact: {after}")


def _rebuild(cursor, table, defaults=None):
    """Recreate one table from the current schema, copying what it already holds.

    SQLite cannot drop a column named in a CHECK constraint (`jobs.status`) or
    widen a UNIQUE constraint in place (`applications.job_id`), so this follows
    the create/copy/drop/rename dance from the SQLite docs. `defaults` supplies
    SQL literals for columns the old table does not have — user_id, here.
    """
    defaults = defaults or {}
    old_columns = _cursor_columns(cursor, table.name)
    temp_name = f"{table.name}_migrating"

    # The copy needs its FK targets alongside it: a Table rendered into an empty
    # MetaData cannot resolve ForeignKey("users.id") and refuses to compile.
    # Only `new_table` is ever compiled, so the copies are just resolution
    # scaffolding — including the ones whose own FKs point back at `table`.
    staging = MetaData()
    for other in table.metadata.tables.values():
        if other.name != table.name:
            other.to_metadata(staging)
    new_table = table.to_metadata(staging, name=temp_name)
    cursor.execute(str(CreateTable(new_table).compile(dialect=_DIALECT)))

    targets, sources = [], []
    for column in table.columns:
        quoted = f'"{column.name}"'
        if column.name in old_columns:
            targets.append(quoted)
            sources.append(quoted)
        elif column.name in defaults:
            targets.append(quoted)
            sources.append(str(defaults[column.name]))

    cursor.execute(
        f"INSERT INTO {temp_name} ({', '.join(targets)}) "
        f"SELECT {', '.join(sources)} FROM {table.name}"
    )
    copied = cursor.execute(f"SELECT COUNT(*) FROM {temp_name}").fetchone()[0]

    cursor.execute(f"DROP TABLE {table.name}")
    cursor.execute(f"ALTER TABLE {temp_name} RENAME TO {table.name}")
    for index in table.indexes:
        cursor.execute(str(CreateIndex(index).compile(dialect=_DIALECT)))

    dropped = sorted(old_columns - {c.name for c in table.columns})
    print(f"{table.name}: rebuilt, {copied} rows copied"
          + (f", dropped {dropped}" if dropped else ""))


def rebuild_tables(db_path, user_id):
    """Rewrite jobs/applications/application_events into their new shape.

    Runs on its own sqlite3 connection in autocommit mode: `PRAGMA foreign_keys`
    cannot be changed inside a transaction, and the SQLite-documented rebuild
    procedure requires it off. Everything else is wrapped in one explicit
    transaction, so a failure anywhere leaves the database untouched.
    """
    raw = sqlite3.connect(str(db_path), timeout=10, isolation_level=None)
    try:
        raw.execute("PRAGMA foreign_keys=OFF")
        cursor = raw.cursor()
        cursor.execute("BEGIN")
        try:
            _rebuild(cursor, db.jobs)
            _rebuild(cursor, db.applications, defaults={"user_id": user_id})
            _rebuild(cursor, db.application_events, defaults={"user_id": user_id})
            if _cursor_has_table(cursor, "settings"):
                cursor.execute("DROP TABLE settings")
                print("settings: dropped (copied into user_settings above)")

            violations = cursor.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"foreign key check failed: {violations[:5]}")
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise
    finally:
        raw.execute("PRAGMA foreign_keys=ON")
        raw.close()


def move_resume(user_id):
    """CVs are personal data — one file per user instead of one shared cv.pdf."""
    legacy, target = config.LEGACY_RESUME_PDF, config.resume_path(user_id)
    if not legacy.is_file() or target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy), str(target))
    print(f"resume: {legacy.name} → {target.relative_to(config.DATA_DIR)}")


def migrate_multiuser(conn):
    """The whole step 2, or nothing if it has already run."""
    if not needs_multiuser_migration(conn):
        print("multi-tenancy: already migrated, nothing to do")
        return db.ensure_local_user(conn)

    if conn.dialect != "sqlite":
        raise RuntimeError(
            f"the multi-tenant migration rewrites tables in place and is SQLite-only; "
            f"this connection is {conn.dialect}. A fresh deployment gets the new schema "
            "from init_schema() and does not need it."
        )

    user_id = db.ensure_local_user(conn)
    print(f"local user: id={user_id} ({config.LOCAL_USER_EMAIL})")

    lift_per_user_data(conn, user_id)
    conn.close()  # the rebuild needs exclusive access to the file
    rebuild_tables(config.DB_PATH, user_id)
    move_resume(user_id)
    return user_id


def main():
    conn = db.get_conn()
    db.init_schema(conn)  # creates the new tables, adds additive columns

    user_id = migrate_multiuser(conn)

    conn = db.get_conn()  # migrate_multiuser closes its connection to rebuild
    before = {
        (row["user_id"], row["status"]): row["n"]
        for row in conn.execute(
            "SELECT user_id, status, COUNT(*) AS n FROM user_jobs GROUP BY user_id, status"
        )
    }

    backfill_posted(conn)
    backfill_salary(conn)
    update_enabled_sources(conn, user_id)

    after = {
        (row["user_id"], row["status"]): row["n"]
        for row in conn.execute(
            "SELECT user_id, status, COUNT(*) AS n FROM user_jobs GROUP BY user_id, status"
        )
    }
    assert before == after, f"status counts changed! {before} → {after}"
    print(f"status counts unchanged: {after}")
    conn.close()


if __name__ == "__main__":
    main()

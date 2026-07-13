"""One-time import of the legacy CSV data into SQLite.

Reads data/{jobs,applied,user}.csv and data/resume.txt (never writes them),
dedupes jobs by Offer_ID, maps legacy statuses, seeds settings, and scores
everything. Idempotent: re-running never duplicates rows or overwrites
settings you have since edited in the UI.

Usage: python3 -m jobmatch.migrate_csv
"""

import csv
import datetime
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import config
from . import db, scoring

JOBS_CSV = config.DATA_DIR / "jobs.csv"
APPLIED_CSV = config.DATA_DIR / "applied.csv"
USER_CSV = config.DATA_DIR / "user.csv"
RESUME_TXT = config.DATA_DIR / "resume.txt"

# Legacy Status → new status. 'x' means "triaged away" (auto-filtered or
# passed on in choose.py) → hidden as declined per user decision.
STATUS_MAP = {"": "new", "x": "declined", "applied": "applied", "rejected": "declined"}
STATUS_STRENGTH = {"applied": 3, "rejected": 2, "x": 1, "": 0}

csv.field_size_limit(sys.maxsize)


def canonical_link(link):
    parts = urlsplit((link or "").strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def clean_field(value):
    value = (value or "").strip()
    return None if value.lower() in ("", "n/a", "nan") else value


def best_row(rows):
    """Among duplicate Offer_ID rows pick: has description, then strongest status."""
    def rank(row):
        has_desc = 1 if (row.get("Description") or "").strip() else 0
        strength = STATUS_STRENGTH.get((row.get("Status") or "").strip().lower(), 0)
        return (has_desc, strength)
    return max(rows, key=rank)


def import_jobs(conn):
    if not JOBS_CSV.is_file():
        print(f"skip: {JOBS_CSV} not found")
        return 0

    by_offer = {}
    total_rows = 0
    with JOBS_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            oid = (row.get("Offer_ID") or "").strip()
            if not oid:
                continue
            total_rows += 1
            by_offer.setdefault(oid, []).append(row)

    scraped_at = datetime.datetime.fromtimestamp(
        JOBS_CSV.stat().st_mtime
    ).isoformat(timespec="seconds")

    inserted = 0
    for oid, rows in by_offer.items():
        row = best_row(rows)
        legacy_status = (row.get("Status") or "").strip().lower()
        skills = clean_field(row.get("Skills")) or ""
        cur = conn.execute(
            """INSERT OR IGNORE INTO jobs
               (source, source_id, title, company, location, salary, freshness,
                link, description, skills, worktype, seniority, employment_type,
                status, scraped_at)
               VALUES ('profesia', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                oid,
                clean_field(row.get("Title")),
                clean_field(row.get("Company")),
                clean_field(row.get("Location")),
                clean_field(row.get("Salary")),
                clean_field(row.get("Freshness")),
                canonical_link(row.get("Link")),
                (row.get("Description") or "").strip(),
                skills.lower(),
                clean_field(row.get("Worktype")),
                clean_field(row.get("Seniority")),
                clean_field(row.get("EmploymentType")),
                STATUS_MAP.get(legacy_status, "new"),
                scraped_at,
            ),
        )
        inserted += cur.rowcount
    conn.commit()
    print(f"jobs.csv: {total_rows} rows → {len(by_offer)} unique offers, {inserted} inserted")
    return inserted


def import_applications(conn):
    applied_ids = set()

    if APPLIED_CSV.is_file():
        with APPLIED_CSV.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                m = re.search(r"/O(\d+)", row.get("Link") or "")
                if m:
                    applied_ids.add(m.group(1))
        applied_date = datetime.date.fromtimestamp(APPLIED_CSV.stat().st_mtime).isoformat()
    else:
        applied_date = datetime.date.today().isoformat()

    # Union with jobs already imported as status=applied
    for row in conn.execute("SELECT source_id FROM jobs WHERE status = 'applied'"):
        applied_ids.add(row["source_id"])

    created = 0
    for oid in sorted(applied_ids):
        job = conn.execute(
            "SELECT id FROM jobs WHERE source = 'profesia' AND source_id = ?", (oid,)
        ).fetchone()
        if not job:
            continue
        conn.execute("UPDATE jobs SET status = 'applied' WHERE id = ?", (job["id"],))
        cur = conn.execute(
            """INSERT OR IGNORE INTO applications (job_id, applied_at, notes)
               VALUES (?, ?, 'imported from applied.csv')""",
            (job["id"], applied_date),
        )
        created += cur.rowcount
    conn.commit()
    print(f"applications: {len(applied_ids)} applied offers found, {created} created")
    return created


def seed_settings(conn):
    """Seed settings only for keys not already present (INSERT OR IGNORE)."""
    seeds = {}

    if USER_CSV.is_file():
        with USER_CSV.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if rows:
            user = rows[0]
            location = clean_field(user.get("Location"))
            seniority = clean_field(user.get("Seniority"))
            worktype = clean_field(user.get("Worktype"))
            skills = clean_field(user.get("Skills"))
            if location:
                seeds["user_location"] = location.lower()
            if seniority:
                seeds["user_seniority"] = seniority.lower()
            if worktype:
                seeds["user_worktype"] = worktype.lower()
            if skills:
                seeds["user_skills"] = sorted(
                    {s.strip().lower() for s in skills.split(",") if s.strip()}
                )

    if RESUME_TXT.is_file():
        seeds["resume_text"] = RESUME_TXT.read_text(encoding="utf-8").strip()

    for key, value in db.DEFAULT_SETTINGS.items():
        seeds.setdefault(key, value)

    seeded = 0
    for key, value in seeds.items():
        cur = conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        seeded += cur.rowcount
    conn.commit()
    print(f"settings: {seeded} keys seeded ({len(seeds) - seeded} already present)")


def summary(conn):
    print("\n── database summary " + "─" * 40)
    for row in conn.execute(
        "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status ORDER BY n DESC"
    ):
        print(f"  jobs {row['status']:>9}: {row['n']}")
    total = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
    apps = conn.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"]
    scored = conn.execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE match_score IS NOT NULL"
    ).fetchone()["n"]
    print(f"  jobs     total: {total}")
    print(f"  applications  : {apps}")
    print(f"  jobs scored   : {scored}")


def main():
    config.DATA_DIR.mkdir(exist_ok=True)
    conn = db.get_conn()
    db.init_schema(conn)

    import_jobs(conn)
    import_applications(conn)
    seed_settings(conn)

    n = scoring.rescore_all(conn)
    print(f"scoring: {n} jobs rescored")

    summary(conn)
    conn.close()


if __name__ == "__main__":
    main()

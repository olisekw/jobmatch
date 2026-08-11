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


def import_jobs(conn, user_id):
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
    legacy_statuses = {}
    for oid, rows in by_offer.items():
        row = best_row(rows)
        legacy_status = (row.get("Status") or "").strip().lower()
        skills = clean_field(row.get("Skills")) or ""
        inserted += conn.execute(
            """INSERT INTO jobs
               (source, source_id, title, company, location, salary, freshness,
                link, description, skills, worktype, seniority, employment_type,
                scraped_at)
               VALUES ('profesia', :source_id, :title, :company, :location, :salary,
                       :freshness, :link, :description, :skills, :worktype,
                       :seniority, :employment_type, :scraped_at)
               ON CONFLICT (source, source_id) DO NOTHING""",
            {
                "source_id": oid,
                "title": clean_field(row.get("Title")),
                "company": clean_field(row.get("Company")),
                "location": clean_field(row.get("Location")),
                "salary": clean_field(row.get("Salary")),
                "freshness": clean_field(row.get("Freshness")),
                "link": canonical_link(row.get("Link")),
                "description": (row.get("Description") or "").strip(),
                "skills": skills.lower(),
                "worktype": clean_field(row.get("Worktype")),
                "seniority": clean_field(row.get("Seniority")),
                "employment_type": clean_field(row.get("EmploymentType")),
                "scraped_at": scraped_at,
            },
        ).rowcount
        # The job is global; the legacy triage decision belongs to this user.
        legacy_statuses[oid] = STATUS_MAP.get(legacy_status, "new")
    conn.commit()

    db.ensure_user_jobs(conn, user_id)
    conn.executemany(
        """UPDATE user_jobs SET status = :status
           WHERE user_id = :user_id AND status = 'new' AND job_id = (
               SELECT id FROM jobs WHERE source = 'profesia' AND source_id = :source_id
           )""",
        [
            {"user_id": user_id, "source_id": oid, "status": status}
            for oid, status in legacy_statuses.items()
            if status != "new"
        ],
    )
    conn.commit()
    print(f"jobs.csv: {total_rows} rows → {len(by_offer)} unique offers, {inserted} inserted")
    return inserted


def import_applications(conn, user_id):
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

    # Union with jobs this user has already triaged as applied
    for row in conn.execute(
        """SELECT j.source_id FROM jobs j JOIN user_jobs uj ON uj.job_id = j.id
           WHERE uj.user_id = :user_id AND uj.status = 'applied'""",
        {"user_id": user_id},
    ):
        applied_ids.add(row["source_id"])

    created = 0
    for oid in sorted(applied_ids):
        job_id = conn.scalar(
            "SELECT id FROM jobs WHERE source = 'profesia' AND source_id = :source_id",
            {"source_id": oid},
        )
        if job_id is None:
            continue
        params = {"user_id": user_id, "job_id": job_id, "applied_at": applied_date}
        conn.execute(
            "UPDATE user_jobs SET status = 'applied' "
            "WHERE user_id = :user_id AND job_id = :job_id",
            {"user_id": user_id, "job_id": job_id},
        )
        created += conn.execute(
            """INSERT INTO applications (user_id, job_id, applied_at, notes)
               VALUES (:user_id, :job_id, :applied_at, 'imported from applied.csv')
               ON CONFLICT (user_id, job_id) DO NOTHING""",
            params,
        ).rowcount
    conn.commit()
    print(f"applications: {len(applied_ids)} applied offers found, {created} created")
    return created


def seed_settings(conn, user_id):
    """Seed settings only for keys this user does not already have."""
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

    seeded = conn.executemany(
        "INSERT INTO user_settings (user_id, key, value) "
        "VALUES (:user_id, :key, :value) ON CONFLICT (user_id, key) DO NOTHING",
        [
            {"user_id": user_id, "key": key, "value": json.dumps(value)}
            for key, value in seeds.items()
        ],
    )
    conn.commit()
    print(f"settings: {seeded} keys seeded ({len(seeds) - seeded} already present)")


def summary(conn, user_id):
    print("\n── database summary " + "─" * 40)
    for row in conn.execute(
        "SELECT status, COUNT(*) AS n FROM user_jobs WHERE user_id = :user_id "
        "GROUP BY status ORDER BY n DESC",
        {"user_id": user_id},
    ):
        print(f"  jobs {row['status']:>9}: {row['n']}")
    counts = {
        "jobs     total": "SELECT COUNT(*) FROM jobs",
        "applications  ": "SELECT COUNT(*) FROM applications WHERE user_id = :user_id",
        "jobs scored   ": "SELECT COUNT(*) FROM user_jobs "
                          "WHERE user_id = :user_id AND match_score IS NOT NULL",
    }
    for label, sql in counts.items():
        print(f"  {label}: {conn.scalar(sql, {'user_id': user_id})}")


def main():
    config.DATA_DIR.mkdir(exist_ok=True)
    conn = db.get_conn()
    db.init_schema(conn)
    user_id = db.ensure_local_user(conn)

    import_jobs(conn, user_id)
    import_applications(conn, user_id)
    seed_settings(conn, user_id)

    n = scoring.rescore_user(conn, user_id)
    print(f"scoring: {n} jobs rescored")

    summary(conn, user_id)
    conn.close()


if __name__ == "__main__":
    main()

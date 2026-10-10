"""Run JobMatch yourself, from the terminal — no server, no account, no shared crawl.

    python3 -m jobmatch.cli scan
    python3 -m jobmatch.cli resume path/to/cv.pdf
    python3 -m jobmatch.cli settings
    python3 -m jobmatch.cli settings weight_skill=0.4 user_location=Bratislava
    python3 -m jobmatch.cli jobs --min-score 50 --limit 20
    python3 -m jobmatch.cli status 412 applied

One account owns everything: `config.LOCAL_USER_EMAIL`, created on first use by
`db.ensure_local_user` — the same function Phase 3 left behind so a database that
predates auth still has an owner, reused here for the opposite reason. Nobody logs
in, nothing is shared between strangers, and the scrape this runs is yours alone —
your own terms, your own schedule, your own IP doing the politeness delays. `scan`
and `scoring` are the exact modules the web app and the worker use: a scan queued,
claimed and run here is indistinguishable from one the worker claimed, which is
what lets this skip straight to `scan.run_claimed` instead of re-implementing it.
"""

import argparse
import logging
import pathlib
import shutil
import sys

import config

from . import db, display, obs, resume, salary, scan, scoring

log = logging.getLogger("jobmatch.cli")

PDF_MAGIC = b"%PDF-"  # every PDF starts with it; a renamed .exe does not


def _local_user(conn):
    db.init_schema(conn)
    return db.ensure_local_user(conn)


def cmd_scan(conn, args):
    user_id = _local_user(conn)
    _status, error = scan.enqueue(conn, user_id=user_id, trigger="cli")
    if error:
        print(error)
        return 1
    row = scan.claim_next(conn, claimed_by="cli")
    if row is None:
        print("Could not claim the scan that was just queued.")
        return 1
    print(f"Scanning as scan #{row['id']} — this can take a few minutes "
          "(the boards are scraped politely, with delays between requests).")
    result = scan.run_claimed(conn, row)
    print(f"{result['status']}: {result['found']} found, {result['enriched']} enriched, "
          f"{result['failed']} failed")
    for source, text in result["source_errors"].items():
        print(f"  {source}: {text}")
    if result["status"] != "done":
        return 1
    print("Run `python3 -m jobmatch.cli jobs` to see your matches.")
    return 0


def cmd_resume(conn, args):
    user_id = _local_user(conn)
    source = pathlib.Path(args.path).expanduser()
    if not source.is_file():
        print(f"No file at {source}")
        return 1
    with open(source, "rb") as fh:
        if fh.read(len(PDF_MAGIC)) != PDF_MAGIC:
            print("That file is not a PDF.")
            return 1

    dest = config.resume_path(user_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, dest)
    text = resume.pdf_to_text(dest)
    if not text.strip():
        print("That PDF has no text in it — it looks like a scan or a set of images.")
        return 1

    skills = resume.skills_from_text(text)
    existing = set(db.get_setting(conn, user_id, "user_skills") or [])
    merged = sorted(existing | set(skills))
    db.set_settings(conn, user_id, {"resume_text": text, "user_skills": merged})
    scoring.rescore_user(conn, user_id)
    print(f"Read {source.name}: {len(skills)} skill(s) found, {len(merged)} stored in total.")
    return 0


def _coerce(key, raw):
    """A settings value as the type `db.DEFAULT_SETTINGS` already says it is."""
    default = db.DEFAULT_SETTINGS.get(key)
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, list):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return raw


def cmd_settings(conn, args):
    user_id = _local_user(conn)
    if not args.pairs:
        settings = db.get_all_settings(conn, user_id)
        for key in sorted(settings):
            print(f"{key} = {settings[key]!r}")
        return 0

    updates = {}
    for pair in args.pairs:
        if "=" not in pair:
            print(f"Expected key=value, got {pair!r}")
            return 1
        key, raw = pair.split("=", 1)
        key = key.strip()
        if key not in db.DEFAULT_SETTINGS:
            print(f"Unknown setting: {key}")
            return 1
        try:
            updates[key] = _coerce(key, raw)
        except ValueError:
            print(f"Could not parse a value for {key}: {raw!r}")
            return 1

    db.set_settings(conn, user_id, updates)
    scoring.rescore_user(conn, user_id)
    print(f"Updated {', '.join(sorted(updates))}.")
    return 0


def cmd_jobs(conn, args):
    user_id = _local_user(conn)
    where, params = ["uj.user_id = :user_id"], {"user_id": user_id}
    if args.status:
        where.append("uj.status = :status")
        params["status"] = args.status
    if args.min_score is not None:
        where.append("uj.match_score IS NOT NULL AND uj.match_score >= :min_score")
        params["min_score"] = args.min_score

    order = db.JOB_ORDER.get(args.sort, db.JOB_ORDER["score"])
    rows = conn.execute(
        f"""SELECT j.id, j.title, j.company, j.location, j.worktype, j.posted_at,
                   j.scraped_at, j.salary_min, j.salary_max, j.salary_currency,
                   j.salary_period, j.link, uj.status, uj.match_score
            FROM jobs j JOIN user_jobs uj ON uj.job_id = j.id
            WHERE {" AND ".join(where)}
            ORDER BY {order} LIMIT :limit""",
        dict(params, limit=args.limit),
    ).fetchall()

    if not rows:
        print("No jobs match. Run `python3 -m jobmatch.cli scan` first?")
        return 0
    for row in rows:
        score = "?" if row["match_score"] is None else f"{row['match_score']:.0f}"
        pay = salary.range_display(row["salary_min"], row["salary_max"],
                                    row["salary_currency"], row["salary_period"]) or ""
        age = display.relative_date(row["posted_at"] or row["scraped_at"])
        worktype = display.label(display.WORKTYPE, row["worktype"])
        print(f"[{row['id']:>5}] {score:>3}  {row['title']} — {row['company']} "
              f"({row['location']}, {worktype}) {pay} {age}")
        print(f"        {row['status']}  {row['link']}")
    return 0


def cmd_status(conn, args):
    user_id = _local_user(conn)
    moved = conn.execute(
        "UPDATE user_jobs SET status = :status WHERE user_id = :user_id AND job_id = :job_id",
        {"status": args.new_status, "user_id": user_id, "job_id": args.job_id},
    ).rowcount
    conn.commit()
    if not moved:
        print(f"No job #{args.job_id} found for you.")
        return 1
    print(f"Job #{args.job_id} marked {args.new_status}.")
    return 0


COMMANDS = {
    "scan": cmd_scan,
    "resume": cmd_resume,
    "settings": cmd_settings,
    "jobs": cmd_jobs,
    "status": cmd_status,
}


def build_parser():
    parser = argparse.ArgumentParser(prog="python3 -m jobmatch.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="Scrape the boards right now, for you alone.")

    p_resume = sub.add_parser("resume", help="Read a CV and extract skills from it.")
    p_resume.add_argument("path", help="Path to a PDF resume.")

    p_settings = sub.add_parser("settings", help="Show or change your preferences.")
    p_settings.add_argument("pairs", nargs="*", metavar="key=value",
                             help="e.g. weight_skill=0.4 user_location=Bratislava")

    p_jobs = sub.add_parser("jobs", help="List your scored jobs.")
    p_jobs.add_argument("--status", choices=db.JOB_STATUSES)
    p_jobs.add_argument("--min-score", type=float, dest="min_score")
    p_jobs.add_argument("--limit", type=int, default=25)
    p_jobs.add_argument("--sort", choices=sorted(db.JOB_ORDER), default="score")

    p_status = sub.add_parser("status", help="Mark one job new, applied or declined.")
    p_status.add_argument("job_id", type=int)
    p_status.add_argument("new_status", choices=db.JOB_STATUSES)

    return parser


def main(argv=None):
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    obs.setup_logging(component="cli")
    conn = db.get_conn()
    try:
        return COMMANDS[args.command](conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

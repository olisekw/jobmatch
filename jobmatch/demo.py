"""The public demo account — seeded, playable, and put back every night.

    python3 -m jobmatch.demo            # create or re-seed it, then say what it holds
    python3 -m jobmatch.demo --status   # when it was last reset, and whether one is due

Most people who open the URL will not sign up, so the demo *is* the product
for them. Two decisions follow from that:

- **It is not read-only.** A demo where the sliders do not move and nothing can
  be triaged shows a screenshot, not an app. Visitors get a real account and can
  change weights, decline jobs and move applications along the pipeline — which
  is safe precisely because the next reset undoes it.
- **Reset is a query, not a timer** — the same reasoning as the scan schedule in
  `jobmatch.worker`: "is the last reset older than DEMO_RESET_HOURS?" survives a
  restart, cannot drift, and cannot double-fire if a second worker exists.

Three things the demo account may *not* do, because they outlast a reset or
are not the visitor's to spend: upload a CV (a public PDF drop box, and the
seeded skills are the point), delete itself, and trigger a scan — the last one
falls out of `is_admin = 0` and needs no special case.

The account keeps its id and its password hash across a reset. Wiping the row
itself would end every session open on it, which on a demo means whoever is
reading the page at 03:00 is thrown out mid-click.
"""

import logging
import sys
from datetime import timedelta

import config

from . import auth, db, display, scoring

log = logging.getLogger("jobmatch.demo")

# Written into `user_settings` after each reset, and read by `due_for_reset`.
# Safe to keep next to real settings: `app.api_settings_put` only writes keys
# that are in `db.DEFAULT_SETTINGS`, so a visitor cannot postpone their own
# reset by PUTting this one.
RESET_KEY = "demo_reset_at"

# Who the demo is meant to be. Chosen so every one of the four score components
# has something to say — an empty preference scores as "not known", which is
# correct behaviour and a dull thing to show somebody.
SEEDED_SETTINGS = {
    "user_location": "bratislava",
    "user_seniority": "medior",
    "user_worktype": "remote",
    "min_match_score": 25,
    "seniority_strict": False,
    "user_skills": [
        "css", "docker", "git", "graphql", "html", "javascript", "node.js",
        "postgresql", "python", "react", "redux", "rest", "sql", "typescript",
    ],
    # Normally written by a CV upload. The demo cannot upload one, so the text
    # that would have come out of `resume.pdf_to_text` is seeded directly —
    # Settings shows it, and it is what makes the Skills bar mean something.
    "resume_text": (
        "Demo User — Frontend / full-stack developer, Bratislava\n"
        "Four years building React and TypeScript interfaces on Node.js and "
        "Python back ends, with PostgreSQL behind them. Comfortable with REST "
        "and GraphQL APIs, Docker, and Git-based CI. Looking for remote work.\n"
        "This CV is part of the demo account and is replaced every night."
    ),
}

# How the seeded tracker reads: enough rows to show the pipeline, each at a
# different stage, and back-dated so the dates are not all today.
# (application status, days ago, note on the event that got it there)
SEEDED_APPLICATIONS = [
    ("interview", 3, "Screening call went well — technical round on Thursday."),
    ("applied", 6, ""),
    ("offer", 11, "Offer received. Negotiating the start date."),
    ("rejected", 18, "Went with someone more senior."),
    ("no_response", 27, "Three weeks, nothing back."),
]

# Jobs the demo has declined, so the Jobs page has a triage history rather than
# a list where every row is untouched.
DECLINED_COUNT = 4


def enabled():
    """Whether this instance offers a demo at all."""
    return config.DEMO_MODE


def is_demo_email(email):
    return auth.normalize_email(email) == config.DEMO_EMAIL


def demo_user(conn):
    """The demo account row, or None if this instance has never seeded one."""
    return db.get_user_by_email(conn, config.DEMO_EMAIL)


def ensure_seeded(conn):
    """The demo account row, seeded on the spot if this instance has none.

    The cold-start path: a freshly deployed box may well serve its first
    visitor before the worker's idle pass has come round, and "the demo account
    must work from a cold start" is the whole point of the phase. Two visitors
    arriving at once race on the unique email — the loser re-reads the row the
    winner made, which is the same row it wanted.
    """
    row = demo_user(conn)
    if row is not None:
        return row
    try:
        reset(conn)
    except Exception:
        log.exception("seeding the demo account failed")
        conn.rollback()
    return demo_user(conn)


def ensure_account(conn):
    """The demo account, created if this instance has not got one. Returns its id.

    Never an admin: that is what keeps a visitor from triggering the shared
    crawl, and it means one fewer special case in `app.api_scan_start`.
    """
    row = demo_user(conn)
    if row is not None:
        if row["is_admin"]:
            # It should never have been one; say so rather than leave it.
            conn.execute("UPDATE users SET is_admin = 0 WHERE id = :id", {"id": row["id"]})
            conn.commit()
            log.warning("demo account was an admin — demoted")
        return row["id"]
    user_id = db.create_user(
        conn, config.DEMO_EMAIL, auth.hash_password(config.DEMO_PASSWORD), is_admin=False
    )
    conn.commit()
    log.info("created the demo account %s (user %d)", config.DEMO_EMAIL, user_id)
    return user_id


def reset(conn):
    """Put the demo account back to its seeded state. Returns a summary dict.

    Idempotent by construction: everything the account owns is deleted first,
    so running this twice in a row leaves exactly the same rows as running it
    once. The account row itself survives — see the module docstring.
    """
    user_id = ensure_account(conn)
    # A visitor may well have changed the password-shaped things around it, but
    # never the hash itself; re-set it anyway, so a demo whose password was
    # changed out of band from the shell comes back to the published one.
    db.set_password(conn, user_id, auth.hash_password(config.DEMO_PASSWORD))

    db.reset_user_data(conn, user_id)
    conn.commit()

    db.ensure_user_jobs(conn, user_id)
    db.set_settings(conn, user_id, SEEDED_SETTINGS)
    scoring.rescore_user(conn, user_id)

    applied = _seed_applications(conn, user_id)
    declined = _seed_declined(conn, user_id, skip=applied)
    db.set_setting(conn, user_id, RESET_KEY, display.utcnow().isoformat(" ", "seconds"))

    summary = {
        "user_id": user_id,
        "jobs": conn.scalar(
            "SELECT COUNT(*) FROM user_jobs WHERE user_id = :u", {"u": user_id}
        ),
        "applications": len(applied),
        "declined": len(declined),
    }
    log.info(
        "demo reset: %(jobs)s jobs, %(applications)s applications, %(declined)s declined",
        summary,
    )
    return summary


def _top_jobs(conn, user_id, limit):
    """The demo's best matches — what a visitor sees at the top of the Jobs page.

    Seeding off the *scored* order rather than off arbitrary ids is what makes
    the tracker look like it came from using the app: the jobs in it are the
    ones the app would have recommended.
    """
    return [
        row["job_id"]
        for row in conn.execute(
            """SELECT job_id FROM user_jobs
               WHERE user_id = :u AND match_score IS NOT NULL
               ORDER BY match_score DESC, job_id
               LIMIT :limit""",
            {"u": user_id, "limit": limit},
        )
    ]


def _seed_applications(conn, user_id):
    """Walk a handful of jobs down the pipeline, with the events to match."""
    job_ids = _top_jobs(conn, user_id, len(SEEDED_APPLICATIONS))
    seeded = []
    today = display.utcnow()
    for job_id, (status, days_ago, note) in zip(job_ids, SEEDED_APPLICATIONS):
        applied_at = (today - timedelta(days=days_ago)).date().isoformat()
        app_id = conn.scalar(
            """INSERT INTO applications (user_id, job_id, applied_at, status)
               VALUES (:user_id, :job_id, :applied_at, :status) RETURNING id""",
            {"user_id": user_id, "job_id": job_id,
             "applied_at": applied_at, "status": status},
        )
        conn.execute(
            "UPDATE user_jobs SET status = 'applied' "
            "WHERE user_id = :user_id AND job_id = :job_id",
            {"user_id": user_id, "job_id": job_id},
        )
        # The row that says it was applied to, and — where it has moved on — the
        # one that says when. An application with no history reads as fake.
        _add_event(conn, user_id, app_id, None, "applied",
                   (today - timedelta(days=days_ago)))
        if status != "applied":
            _add_event(conn, user_id, app_id, "applied", status,
                       (today - timedelta(days=max(0, days_ago - 2))), note)
        seeded.append(job_id)
    conn.commit()
    return seeded


def _add_event(conn, user_id, app_id, from_status, to_status, when, note=None):
    conn.execute(
        """INSERT INTO application_events
               (user_id, application_id, event_at, from_status, to_status, note)
           VALUES (:user_id, :app_id, :event_at, :from_status, :to_status, :note)""",
        {"user_id": user_id, "app_id": app_id,
         "event_at": when.isoformat(" ", "seconds"),
         "from_status": from_status, "to_status": to_status, "note": note},
    )


def _seed_declined(conn, user_id, skip=()):
    """A few declined jobs, taken from further down the list than the applications."""
    candidates = [
        job_id
        for job_id in _top_jobs(conn, user_id, len(SEEDED_APPLICATIONS) + DECLINED_COUNT * 3)
        if job_id not in set(skip)
    ]
    # Every third one, so the declines are scattered through the list rather
    # than a solid block at the top of it.
    chosen = candidates[2::3][:DECLINED_COUNT]
    for job_id in chosen:
        conn.execute(
            "UPDATE user_jobs SET status = 'declined' "
            "WHERE user_id = :user_id AND job_id = :job_id",
            {"user_id": user_id, "job_id": job_id},
        )
    conn.commit()
    return chosen


# ── The nightly schedule ─────────────────────────────────────

def last_reset(conn, user_id=None):
    """When the demo was last put back, as a datetime, or None."""
    if user_id is None:
        row = demo_user(conn)
        if row is None:
            return None
        user_id = row["id"]
    return display.parse(db.get_setting(conn, user_id, RESET_KEY))


def due_for_reset(conn, now=None):
    """True if the demo exists and its last reset is older than the interval."""
    if not config.DEMO_MODE or config.DEMO_RESET_HOURS <= 0:
        return False
    if demo_user(conn) is None:
        return True  # enabled but never seeded — the first pass creates it
    when = last_reset(conn)
    if when is None:
        return True
    now = now or display.utcnow()
    return now - when >= timedelta(hours=config.DEMO_RESET_HOURS)


def maybe_reset(conn):
    """The worker's hook. Returns the summary if it reset, else None."""
    if not due_for_reset(conn):
        return None
    return reset(conn)


# ── CLI ──────────────────────────────────────────────────────

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    conn = db.get_conn()
    try:
        db.init_schema(conn)
        if "--status" in argv:
            row = demo_user(conn)
            if row is None:
                print(f"no demo account ({config.DEMO_EMAIL}) on this database")
                return
            when = last_reset(conn, row["id"])
            print(f"demo account {config.DEMO_EMAIL} is user {row['id']}")
            print(f"  last reset: {when.isoformat(' ', 'seconds') if when else 'never'}")
            print(f"  reset due:  {'yes' if due_for_reset(conn) else 'no'}"
                  f" (every {config.DEMO_RESET_HOURS}h,"
                  f" DEMO_MODE={'on' if config.DEMO_MODE else 'off'})")
            return
        summary = reset(conn)
        print(f"demo account {config.DEMO_EMAIL} is user {summary['user_id']}")
        print(f"  password:     {config.DEMO_PASSWORD}")
        print(f"  jobs:         {summary['jobs']}")
        print(f"  applications: {summary['applications']}")
        print(f"  declined:     {summary['declined']}")
        if not config.DEMO_MODE:
            print("  note: DEMO_MODE is off, so the app will not offer this account")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

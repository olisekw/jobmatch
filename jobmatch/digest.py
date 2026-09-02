"""The email digest of new high-scoring matches.

    python3 -m jobmatch.digest             # send every digest that is due
    python3 -m jobmatch.digest --status    # who is due, and what is waiting for them
    python3 -m jobmatch.digest --dry-run   # build the mail and print it, send nothing
    python3 -m jobmatch.digest --user me@example.com --force   # one user, now

Scanning is the app's only reason to be running when nobody is looking at it,
and until now the only way to find out what it turned up was to open the page.
The digest is the other half: a scan finds a 92% match at 04:00 and the person
it matches hears about it.

**What goes in one.** Exactly what the Jobs page calls a match — `status = 'new'`
and `match_score >= min_match_score` — so the email and the dashboard can never
disagree about what counts. That derivation is not duplicated here; it is the
same clause `app.api_stats` counts with.

**Nothing is sent twice.** `user_jobs.digested_at` is stamped on the rows that
actually went out, so "new to this user" is a fact about what was sent, not a
guess from a timestamp. It has to be stored: a job that crosses the threshold
only because the user moved a weight *is* news to them, and no comparison
against `scraped_at` would ever notice it. Jobs that did not fit in the email
stay unmarked and lead the next one.

**Scheduling is a query, not a timer** — the same reasoning as the scan
schedule and the demo reset in `jobmatch.worker`: "is this user's last digest
older than DIGEST_INTERVAL_HOURS?" survives a restart, cannot drift, and cannot
double-fire if a second worker is ever started.

**The stamp records the attempt, not the success.** It is written before the
send, so a mail server that is refusing connections costs one cycle of latency
rather than a retry every ten seconds for as long as it stays broken. The jobs
themselves are only marked once the message is away, so nothing is *lost* by a
failed send — it all arrives in the next digest.
"""

import argparse
import logging
import sys
from datetime import timedelta
from html import escape

import config

from . import db, demo, display, mail, salary

log = logging.getLogger("jobmatch.digest")

# When the digest last ran for a user — sent or not; see the module docstring.
# Kept in `user_settings` next to their real settings, which is safe because
# `app.api_settings_put` only writes keys that are in `db.DEFAULT_SETTINGS`:
# a user cannot PUT themselves a fresh digest.
RUN_KEY = "digest_run_at"

SETTING_KEY = "digest_enabled"

# The columns an email needs. Deliberately not `jobs.description`: a digest is a
# reason to open the app, not a copy of it.
DIGEST_COLUMNS = """j.id, j.title, j.company, j.location, j.link, j.source,
                    j.worktype, j.seniority, j.employment_type,
                    j.salary, j.salary_min, j.salary_max,
                    j.salary_currency, j.salary_period,
                    uj.match_score"""


def enabled():
    """Whether this instance sends digests at all."""
    return mail.configured() and config.DIGEST_INTERVAL_HOURS > 0


def wants_digest(conn, user_id):
    """Has this user left the digest on?"""
    return bool(db.get_setting(conn, user_id, SETTING_KEY))


def candidates(conn):
    """Every account that could be sent one, oldest first.

    The demo account is excluded here rather than at send time: its address is
    published on the landing page and is nobody's inbox, and a nightly reset
    would hand it the same matches again every single day.
    """
    return [
        row for row in conn.execute("SELECT id, email FROM users ORDER BY id")
        if not demo.is_demo_email(row["email"])
    ]


# ── The schedule ─────────────────────────────────────────────

def last_run(conn, user_id):
    """When this user's digest last ran, as a datetime, or None."""
    return display.parse(db.get_setting(conn, user_id, RUN_KEY))


def due(conn, user_id, now=None):
    """True if this user is owed a look. Says nothing about there being matches.

    A user who has never had one is due immediately — on a box where SMTP has
    just been configured that is the point, and on a fresh signup their first
    digest is the pool ranked for them.
    """
    if not enabled() or not wants_digest(conn, user_id):
        return False
    when = last_run(conn, user_id)
    if when is None:
        return True
    now = now or display.utcnow()
    return now - when >= timedelta(hours=config.DIGEST_INTERVAL_HOURS)


def mark_run(conn, user_id, when=None):
    """Record that the digest ran for this user. Commits."""
    when = when or display.utcnow()
    db.set_setting(conn, user_id, RUN_KEY, when.isoformat(" ", "seconds"))


# ── What goes in one ─────────────────────────────────────────

def pending(conn, user_id, limit=None):
    """→ (rows, total): this user's unsent matches, best first.

    `total` counts every one of them and `rows` is the page that fits in an
    email, so the message can honestly say how many more are waiting.
    """
    limit = config.DIGEST_MAX_JOBS if limit is None else limit
    threshold = float(db.get_all_settings(conn, user_id)["min_match_score"])
    scope = {"user_id": user_id, "threshold": threshold}
    # The same "matched" derivation the dashboard counts with, plus the one
    # thing a digest adds: it has not been sent yet.
    where = """uj.user_id = :user_id
               AND uj.status = 'new'
               AND uj.digested_at IS NULL
               AND uj.match_score IS NOT NULL
               AND uj.match_score >= :threshold"""
    total = conn.scalar(f"SELECT COUNT(*) FROM user_jobs uj WHERE {where}", scope)
    if not total:
        return [], 0
    rows = conn.execute(
        f"""SELECT {DIGEST_COLUMNS}
            FROM user_jobs uj JOIN jobs j ON j.id = uj.job_id
            WHERE {where}
            ORDER BY uj.match_score DESC, COALESCE(j.posted_at, j.scraped_at) DESC
            LIMIT :limit""",
        dict(scope, limit=limit),
    ).fetchall()
    return rows, total


def mark_sent(conn, user_id, job_ids, when=None):
    """Stamp the rows that went out, so no digest ever repeats them. Commits."""
    if not job_ids:
        return 0
    when = (when or display.utcnow()).isoformat(" ", "seconds")
    marked = conn.executemany(
        "UPDATE user_jobs SET digested_at = :when "
        "WHERE user_id = :user_id AND job_id = :job_id AND digested_at IS NULL",
        [{"when": when, "user_id": user_id, "job_id": job_id} for job_id in job_ids],
    )
    conn.commit()
    return marked


# ── Wording it ───────────────────────────────────────────────

def job_url(row):
    """Where "open this job" goes: the app if it has a public address, else the board.

    An email has no request to build a URL from, so `PUBLIC_BASE_URL` is the
    only way the worker can know its own address. Unset — which is every local
    run — links straight to the posting rather than to `http://None/jobs/12`.
    """
    if config.PUBLIC_BASE_URL:
        return f"{config.PUBLIC_BASE_URL}/jobs/{row['id']}"
    return row["link"]


def settings_url():
    return f"{config.PUBLIC_BASE_URL}/settings" if config.PUBLIC_BASE_URL else ""


def score_text(row):
    return f"{round(float(row['match_score'] or 0))}%"


def facts(row):
    """The short line under a title: where, what shape, what it pays."""
    parts = [
        row["company"] or "",
        row["location"] or "",
        display.label(display.WORKTYPE, row["worktype"]),
        display.label(display.SENIORITY, row["seniority"]),
        row["salary"] or salary.hourly_display(
            row["salary_min"], row["salary_max"],
            row["salary_currency"], row["salary_period"],
        ) or "",
    ]
    return " · ".join(part for part in parts if part)


def subject(rows, total):
    """'5 new job matches (top 92%)' — the count and the best score, up front.

    A digest people stop opening is a digest that does not work, and the two
    things worth knowing before opening are how many and how good.
    """
    top = score_text(rows[0]) if rows else "0%"
    noun = "match" if total == 1 else "matches"
    return f"{total} new job {noun} (top {top})"


def text_body(rows, total):
    """The plain-text part — the one a terminal, a reader and a filter all see."""
    lines = [
        f"{total} new {'match' if total == 1 else 'matches'} scored against your profile.",
        "",
    ]
    for row in rows:
        lines.append(f"{score_text(row)}  {row['title'] or 'Untitled role'}")
        detail = facts(row)
        if detail:
            lines.append(f"      {detail}")
        lines.append(f"      {job_url(row)}")
        lines.append("")
    remaining = total - len(rows)
    if remaining > 0:
        lines.append(
            f"…and {remaining} more above your threshold — they are in the next digest, "
            "or on the Jobs page now."
        )
        lines.append("")
    lines.append("— JobMatch")
    if settings_url():
        lines.append(f"Turn these off under Notifications: {settings_url()}")
    return "\n".join(lines)


# Inline styles only: a <style> block is stripped by enough clients that the
# safe assumption is that it will be. Black and white, like the app.
_HTML = """\
<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;
            max-width:620px;margin:0 auto;padding:24px;color:#111;">
  <p style="margin:0 0 20px;font-size:15px;">{intro}</p>
  {jobs}
  {more}
  <p style="margin:28px 0 0;font-size:12px;color:#666;
            border-top:1px solid #e5e5e5;padding-top:12px;">
    JobMatch{footer}
  </p>
</div>"""

_JOB = """\
  <div style="border:1px solid #e5e5e5;border-radius:6px;padding:14px 16px;margin-bottom:12px;">
    <div style="font-size:13px;font-weight:700;letter-spacing:.04em;color:#111;">{score}</div>
    <div style="font-size:16px;font-weight:600;margin:2px 0 4px;">
      <a href="{url}" style="color:#111;text-decoration:none;">{title}</a>
    </div>
    <div style="font-size:13px;color:#555;">{facts}</div>
  </div>"""


def html_body(rows, total):
    """The HTML alternative. Same words as the text part, in boxes."""
    intro = escape(
        f"{total} new {'match' if total == 1 else 'matches'} scored against your profile."
    )
    jobs = "".join(
        _JOB.format(
            score=escape(score_text(row)),
            url=escape(job_url(row), quote=True),
            title=escape(row["title"] or "Untitled role"),
            facts=escape(facts(row)),
        )
        for row in rows
    )
    remaining = total - len(rows)
    more = ""
    if remaining > 0:
        more = (
            '<p style="font-size:13px;color:#555;margin:0 0 8px;">'
            f"…and {remaining} more above your threshold.</p>"
        )
    footer = ""
    if settings_url():
        footer = (
            f' · <a href="{escape(settings_url(), quote=True)}" style="color:#666;">'
            "turn these off</a>"
        )
    return _HTML.format(intro=intro, jobs=jobs, more=more, footer=footer)


def compose(rows, total):
    """→ (subject, text, html) for one user's digest."""
    return subject(rows, total), text_body(rows, total), html_body(rows, total)


# ── Sending ──────────────────────────────────────────────────

def send_for_user(conn, user_id, email, force=False, dry_run=False):
    """Send one user their digest. Returns a summary dict, or None if none was due.

    The order is load-bearing: stamp the run *first* so a relay that is down
    cannot be retried on every poll, then send, then mark the jobs — which is
    what makes a failure cost latency instead of losing the matches.
    """
    if not force and not due(conn, user_id):
        return None
    rows, total = pending(conn, user_id)
    if not dry_run:
        mark_run(conn, user_id)
    if not rows:
        # Nothing to say. An empty digest is worse than no digest: it teaches
        # people that the email is not worth opening.
        log.debug("no new matches for user %d — nothing sent", user_id)
        return None

    subject_line, text, html = compose(rows, total)
    if dry_run:
        return {"user_id": user_id, "email": email, "subject": subject_line,
                "sent": 0, "waiting": total, "text": text, "html": html}

    headers = {}
    if settings_url():
        # Where an unsubscribe *is*, for the clients that offer the button.
        headers["List-Unsubscribe"] = f"<{settings_url()}>"
    mail.send(email, subject_line, text, html=html, headers=headers)
    marked = mark_sent(conn, user_id, [row["id"] for row in rows])
    log.info(
        "digest to %s: %d jobs of %d waiting", email, marked, total,
        extra={"user_id": user_id, "jobs": marked, "waiting": total},
    )
    return {"user_id": user_id, "email": email, "subject": subject_line,
            "sent": marked, "waiting": total}


def send_due(conn, force=False, dry_run=False):
    """Send every digest that is due. Returns the summaries. Never raises.

    One user's bounced address, malformed row or refused connection must not
    stop the others getting theirs, so each send is wrapped — the same reason
    the demo reset is wrapped in the worker.
    """
    # `enabled()` is the *schedule*; sending needs only a mail server. Keeping
    # the two apart is what lets `DIGEST_INTERVAL_HOURS=0` mean "the worker
    # never sends one" while `--force` from the shell still can.
    if not dry_run and not mail.configured():
        return []
    sent = []
    for row in candidates(conn):
        if not force and not wants_digest(conn, row["id"]):
            continue
        try:
            summary = send_for_user(
                conn, row["id"], row["email"], force=force, dry_run=dry_run
            )
        except Exception:
            log.exception("digest to %s failed — the jobs stay unsent", row["email"])
            conn.rollback()
            continue
        if summary:
            sent.append(summary)
    return sent


def maybe_send(conn):
    """The worker's hook. Returns the summaries, or [] when nothing was due."""
    if not enabled():
        return []
    return send_due(conn)


# ── CLI ──────────────────────────────────────────────────────

def _status(conn):
    print(f"digest: {'on' if enabled() else 'off'}"
          f" (SMTP_HOST={config.SMTP_HOST or 'unset'},"
          f" every {config.DIGEST_INTERVAL_HOURS}h,"
          f" up to {config.DIGEST_MAX_JOBS} jobs)")
    if not config.PUBLIC_BASE_URL:
        print("  PUBLIC_BASE_URL is unset — jobs would link to the board, not the app")
    for row in candidates(conn):
        _, total = pending(conn, row["id"])
        when = last_run(conn, row["id"])
        print(f"  {row['email']}")
        print(f"    digest setting: {'on' if wants_digest(conn, row['id']) else 'off'}")
        print(f"    last run:       {when.isoformat(' ', 'seconds') if when else 'never'}")
        print(f"    due now:        {'yes' if due(conn, row['id']) else 'no'}")
        print(f"    waiting:        {total} unsent {'match' if total == 1 else 'matches'}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Send the email digest of new matches.")
    parser.add_argument("--status", action="store_true",
                        help="show who is due and what is waiting, send nothing")
    parser.add_argument("--dry-run", action="store_true",
                        help="build the mail and print it, send nothing and mark nothing")
    parser.add_argument("--user", metavar="EMAIL", help="only this account")
    parser.add_argument("--force", action="store_true",
                        help="ignore the schedule and the per-user setting")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    conn = db.get_conn()
    try:
        db.init_schema(conn)
        if args.status:
            _status(conn)
            return 0
        if not mail.configured() and not args.dry_run:
            print("No SMTP_HOST is configured, so nothing can be sent — see .env.example.")
            return 1

        if args.user:
            row = db.get_user_by_email(conn, args.user)
            if row is None:
                print(f"no account for {args.user}")
                return 1
            summaries = []
            summary = send_for_user(
                conn, row["id"], row["email"], force=args.force, dry_run=args.dry_run
            )
            if summary:
                summaries.append(summary)
        else:
            summaries = send_due(conn, force=args.force, dry_run=args.dry_run)

        if not summaries:
            print("Nothing to send.")
            return 0
        for summary in summaries:
            print(f"{summary['email']}: {summary['subject']}")
            if args.dry_run:
                print()
                print(summary["text"])
            else:
                print(f"  {summary['sent']} jobs sent, {summary['waiting']} were waiting")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

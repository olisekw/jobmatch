"""Scan orchestrator: claim a queued scan → search → enrich → score.

Phase 4 moved execution out of the web process, and `scans` **is** the queue:

- a trigger inserts a `queued` row (`enqueue`) and returns; nothing runs in the
  web process any more;
- `jobmatch.worker` claims that row with a conditional `UPDATE … WHERE
  status = 'queued'`, which is atomic, so two workers can never run one scan;
- progress, the heartbeat and the cancel flag are columns on the row, so any
  web worker can answer `current_status()` and any process can ask for a stop.

Nothing here keeps scan state in module globals. That is the point: a status
poll that lands on a different gunicorn worker than the one that triggered the
scan — or on a machine that does no scanning at all — still answers correctly.

A small SQL-backed queue rather than Redis + Celery. The scans are minutes long
and there is at most one at a time; a second dependency would buy nothing.
"""

import json
import logging
import time
import traceback
from datetime import timedelta

import config

from . import dates, db, display, extract, salary, scoring
from .sources import SOURCES, get_enabled
from .sources.base import ScanContext

log = logging.getLogger("jobmatch.scan")

# A scan in either of these states owns the queue: `enqueue` refuses while one
# exists, which is what keeps two scrapes off the boards at the same time.
ACTIVE_STATUSES = ("queued", "running")


def _now():
    """A timestamp in the shape every stored one has: naive UTC, to the second.

    Written from Python rather than with `datetime('now')` so the queue is one
    fewer dialect gap for Phase 5 to close.
    """
    return display.utcnow().isoformat(sep=" ", timespec="seconds")


# ── The queue ────────────────────────────────────────────────

def enqueue(conn, user_id=None, trigger="manual"):
    """Queue a scan. Returns (status dict, error message) — one is always None.

    The guard is inside the INSERT rather than a SELECT before it, so two web
    workers racing on the same button cannot both get a row through.
    """
    scan_id = conn.scalar(
        """INSERT INTO scans (status, phase, started_at, "trigger", requested_by)
           SELECT 'queued', :phase, :now, :trigger, :user_id
           WHERE NOT EXISTS (
               SELECT 1 FROM scans WHERE status IN ('queued', 'running')
           )
           RETURNING id""",
        {"phase": "Waiting for a worker", "now": _now(),
         "trigger": trigger, "user_id": user_id},
    )
    conn.commit()
    if scan_id is None:
        return None, "A scan is already running."
    log.info("queued scan %d (%s, requested by %s)", scan_id, trigger, user_id)
    return status_of(conn, scan_id), None


def claim_next(conn, claimed_by):
    """Take ownership of the oldest queued scan, or return None.

    `WHERE id = (SELECT …) AND status = 'queued'` is the whole concurrency
    story: the second worker re-checks the status after the first one's UPDATE
    lands and matches no rows, so it claims nothing rather than duplicating.
    """
    now = _now()
    row = conn.execute(
        """UPDATE scans
              SET status = 'running', claimed_by = :claimed_by, phase = 'Starting',
                  started_at = :now, heartbeat_at = :now
            WHERE id = (SELECT id FROM scans WHERE status = 'queued' ORDER BY id LIMIT 1)
              AND status = 'queued'
        RETURNING id, started_at, requested_by, "trigger" """,
        {"claimed_by": claimed_by, "now": now},
    ).fetchone()
    conn.commit()
    return row


def request_stop(conn):
    """Ask the active scan to stop. True if there was one to ask.

    Two cases, because a stop now crosses processes: a *running* scan gets a
    flag its worker picks up at the next heartbeat, while a *queued* one has no
    worker to notice anything and is simply closed out here.
    """
    now = _now()
    stopped = conn.execute(
        "UPDATE scans SET cancel_requested = 1 WHERE status = 'running'"
    ).rowcount
    stopped += conn.execute(
        """UPDATE scans SET status = 'cancelled', phase = 'Cancelled',
               finished_at = :now WHERE status = 'queued'""",
        {"now": now},
    ).rowcount
    conn.commit()
    return stopped > 0


def reconcile_orphans(conn, stale_seconds=None):
    """Close out `running` rows no live worker is heartbeating. Returns how many.

    A worker killed mid-scan leaves its row `running` for ever, and that row
    blocks every later scan. The heartbeat is what separates that from a scan
    still in progress: a live one has written within the last few seconds, so a
    row silent for `SCAN_STALE_SECONDS` belongs to a process that is gone. The
    row is failed rather than requeued — an interrupted scan loses nothing (jobs
    are committed as they are found) and a crash-inducing scan must not loop.
    """
    if stale_seconds is None:
        stale_seconds = config.SCAN_STALE_SECONDS
    cutoff = display.utcnow() - timedelta(seconds=stale_seconds)

    closed = 0
    for row in conn.execute(
        "SELECT id, heartbeat_at, started_at FROM scans WHERE status = 'running'"
    ).fetchall():
        # Rows from before Phase 4 have no heartbeat at all; their start is the
        # last thing known to have happened to them.
        beat = display.parse(row["heartbeat_at"] or row["started_at"])
        if beat is not None and beat > cutoff:
            continue
        closed += conn.execute(
            """UPDATE scans SET status = 'failed', phase = 'Interrupted',
                   finished_at = :now,
                   error = 'the worker running this scan stopped before it finished'
               WHERE id = :id AND status = 'running'""",
            {"now": _now(), "id": row["id"]},
        ).rowcount
    conn.commit()
    if closed:
        log.warning("reconciled %d orphaned running scan(s)", closed)
    return closed


# ── Status, as the client sees it ────────────────────────────

def current_status(conn):
    """The most recent scan, or None on a database that has never scanned."""
    row = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    return _status(row) if row is not None else None


def status_of(conn, scan_id):
    row = conn.execute("SELECT * FROM scans WHERE id = :id", {"id": scan_id}).fetchone()
    return _status(row) if row is not None else None


def _status(row):
    """One scan row as the JSON the poller consumes.

    Deliberately not `dict(row)`: `scans.error` is a traceback, and the same
    reasoning that keeps it out of the dashboard summary keeps it out of here.
    """
    try:
        source_errors = json.loads(row["source_errors"]) if row["source_errors"] else {}
    except ValueError:
        source_errors = {}
    return {
        "scan_id": row["id"],
        "status": row["status"],
        "phase": row["phase"] or "",
        "found": row["found"],
        "enriched": row["enriched"],
        "failed": row["failed"],
        "source_errors": source_errors,
        "started_at": row["started_at"],
        "trigger": row["trigger"],
        "cancelling": bool(row["cancel_requested"]) and row["status"] in ACTIVE_STATUSES,
    }


# ── Running one claimed scan ─────────────────────────────────

class ScanState:
    """Live state of the scan this process is running.

    The counters are held in memory and written out on a throttle rather than
    per row: they are progress, not data, and the scan already commits every
    job it finds. `sync()` is both directions at once — it writes progress and
    reads the cancel flag back, so one round trip per heartbeat covers both.
    """

    def __init__(self, conn, row, should_stop=None):
        self.conn = conn
        self.scan_id = row["id"]
        self.user_id = row["requested_by"]  # whose `matched` count gets recorded
        self.started_at = row["started_at"]
        self.phase = "Starting"
        self.found = 0
        self.enriched = 0
        self.failed = 0
        self.source_errors = {}   # source name → error text
        self.status = "running"   # running | done | failed | cancelled
        self.error = None
        self.stop_requested = False
        # The worker's shutdown flag: a SIGTERM has to stop the scan as surely
        # as a user pressing Cancel, and it never reaches the database.
        self._should_stop = should_stop or (lambda: False)
        # The claim wrote a heartbeat a moment ago, so the clock starts now —
        # not at 0.0, which on a machine whose monotonic clock starts near zero
        # would throttle the first real one instead of letting it through.
        self._last_sync = time.monotonic()

    def set_phase(self, text):
        self.phase = text
        self.sync(force=True)

    def sync(self, force=False):
        """Write progress + heartbeat, read the cancel flag back. Throttled."""
        now = time.monotonic()
        if not force and now - self._last_sync < config.SCAN_HEARTBEAT_SECONDS:
            return
        self._last_sync = now
        try:
            cancelled = self.conn.scalar(
                """UPDATE scans SET phase = :phase, found = :found,
                       enriched = :enriched, failed = :failed, heartbeat_at = :now
                   WHERE id = :id RETURNING cancel_requested""",
                {"phase": self.phase, "found": self.found, "enriched": self.enriched,
                 "failed": self.failed, "now": _now(), "id": self.scan_id},
            )
            self.conn.commit()
        except Exception:
            # A heartbeat that could not be written is worth a log line and
            # nothing more — losing one must not lose the scan.
            log.exception("could not write progress for scan %d", self.scan_id)
            return
        if cancelled:
            self.stop_requested = True

    def stopped(self):
        """Cancellation from either direction: the row's flag or a SIGTERM."""
        if self._should_stop():
            self.stop_requested = True
        elif not self.stop_requested:
            self.sync()
        return self.stop_requested


def run_claimed(conn, row, should_stop=None):
    """Run one claimed scan to completion. Returns its finished status dict."""
    state = ScanState(conn, row, should_stop=should_stop)
    _run_scan(state, conn)
    return status_of(conn, state.scan_id)


def _run_scan(state, conn):
    try:
        # The crawl is shared, so it runs off the admin's search settings, not
        # those of whoever pressed the button. Per-user preferences only ever
        # affect scoring, never what gets fetched.
        settings = db.get_all_settings(conn, db.admin_user_id(conn))
        sources = get_enabled(settings["enabled_sources"])
        terms = [t for t in settings["search_terms"] if str(t).strip()]
        days = int(settings["scan_days"]) or None

        ctx = ScanContext(progress=state.set_phase, stopped=state.stopped)

        if any(s.needs_browser for s in sources) or _browser_enrich_pending(conn):
            # Imported here, not at module scope: the web process imports this
            # module for `enqueue` alone and has no reason to need Playwright.
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
                context = browser.new_context(
                    user_agent=config.USER_AGENT,
                    viewport={"width": 1280, "height": 1024},
                    locale="sk-SK",
                    timezone_id="Europe/Bratislava",
                )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page = context.new_page()

                _search_phase(state, conn, page, sources, terms, days, ctx)
                if not state.stopped():
                    _enrich_phase(state, conn, page, ctx)

                browser.close()
        else:
            # API-only scan: no Playwright needed
            _search_phase(state, conn, None, sources, terms, days, ctx)
            if not state.stopped():
                _enrich_phase(state, conn, None, ctx)

        state.set_phase("Scoring matches")
        # New jobs are new for everyone: materialize and rescore every user.
        scoring.rescore_all_users(conn)

        state.status = "cancelled" if state.stop_requested else "done"
        state.phase = "Cancelled" if state.stop_requested else "Finished"
    except Exception:
        log.exception("scan %d failed", state.scan_id)
        state.status = "failed"
        state.error = traceback.format_exc(limit=3)
        state.phase = "Failed"
    finally:
        _finalize(state, conn)


def _browser_enrich_pending(conn):
    """True if jobs still needing descriptions belong to a browser source."""
    browser_sources = [n for n, s in SOURCES.items() if s.needs_browser]
    if not browser_sources:
        return False
    binds = {f"s{i}": name for i, name in enumerate(browser_sources)}
    marks = ",".join(f":{key}" for key in binds)
    return conn.scalar(
        f"SELECT COUNT(*) FROM jobs WHERE TRIM(description) = '' AND source IN ({marks})",
        binds,
    ) > 0


def _insert_stub(conn, source, stub):
    """Insert one job stub; returns rows inserted (0 if already known)."""
    description = (stub.get("description") or "").strip()
    features = extract.extract_all(description) if description else {
        "skills": "", "worktype": None, "seniority": None, "employment_type": None,
    }
    # Structured fields the board supplied win over regex extraction
    worktype = stub.get("worktype") or features["worktype"]
    seniority = stub.get("seniority") or features["seniority"]
    employment_type = stub.get("employment_type") or features["employment_type"]

    posted_at = stub.get("posted_at") or dates.parse_posted(stub.get("freshness"))

    if "salary_min" in stub or "salary_max" in stub:
        s_min, s_max = stub.get("salary_min"), stub.get("salary_max")
        s_cur, s_per = stub.get("salary_currency"), stub.get("salary_period")
    else:
        s_min, s_max, s_cur, s_per = salary.parse_salary(stub.get("salary"))

    # ON CONFLICT DO NOTHING rather than INSERT OR IGNORE: sqlite 3.24+ and
    # Postgres both speak it, and it only swallows the duplicate-key case
    # instead of every constraint violation.
    result = conn.execute(
        """INSERT INTO jobs
           (source, source_id, title, company, location, salary, freshness, link,
            description, skills, worktype, seniority, employment_type,
            posted_at, salary_min, salary_max, salary_currency, salary_period)
           VALUES (:source, :source_id, :title, :company, :location, :salary,
                   :freshness, :link, :description, :skills, :worktype, :seniority,
                   :employment_type, :posted_at, :salary_min, :salary_max,
                   :salary_currency, :salary_period)
           ON CONFLICT (source, source_id) DO NOTHING""",
        {
            "source": source.name, "source_id": stub["source_id"],
            "title": stub["title"], "company": stub["company"],
            "location": stub["location"], "salary": stub["salary"],
            "freshness": stub["freshness"], "link": stub["link"],
            "description": description, "skills": features["skills"],
            "worktype": worktype, "seniority": seniority,
            "employment_type": employment_type, "posted_at": posted_at,
            "salary_min": s_min, "salary_max": s_max,
            "salary_currency": s_cur, "salary_period": s_per,
        },
    )
    return result.rowcount


def _search_phase(state, conn, page, sources, terms, days, ctx):
    for source in sources:
        if state.stopped():
            return
        if source.needs_browser and page is None:
            state.source_errors[source.name] = "browser unavailable"
            continue
        known_ids = {
            row["source_id"]
            for row in conn.execute(
                "SELECT source_id FROM jobs WHERE source = :source", {"source": source.name}
            )
        }
        state.set_phase(f"Searching {source.label}")
        try:
            stubs = source.search(page, terms, days, known_ids, ctx)
        except Exception as e:
            log.warning("%s search failed: %s", source.name, e)
            state.source_errors[source.name] = f"search: {e}"
            continue

        for stub in stubs:
            state.found += _insert_stub(conn, source, stub)
        conn.commit()


def _enrich_phase(state, conn, page, ctx):
    pending = conn.execute(
        "SELECT id, source, link FROM jobs WHERE TRIM(description) = '' ORDER BY id"
    ).fetchall()

    for i, job in enumerate(pending, 1):
        if state.stopped():
            return
        source = SOURCES.get(job["source"])
        if source is None or (source.needs_browser and page is None):
            continue
        state.set_phase(
            f"Reading job descriptions on {source.label} ({i} of {len(pending)})"
        )

        description = ""
        for attempt in range(config.MAX_RETRIES):
            try:
                description = source.fetch_detail(page, job["link"])
                break
            except Exception:
                if attempt + 1 >= config.MAX_RETRIES:
                    state.failed += 1
                if not ctx.sleep(5, 12):
                    return

        if description:
            features = extract.extract_all(description)
            conn.execute(
                """UPDATE jobs SET description = :description, skills = :skills,
                       worktype = :worktype, seniority = :seniority,
                       employment_type = :employment_type WHERE id = :id""",
                dict(features, description=description, id=job["id"]),
            )
            conn.commit()
            state.enriched += 1

        if not ctx.sleep(config.MIN_DETAIL_DELAY, config.MAX_DETAIL_DELAY):
            return


def _finalize(state, conn):
    try:
        # `scans.matched` is one number for a now per-user quantity, so it
        # records it for whoever asked for the scan (the admin, for scheduled
        # runs) — which is exactly the dashboard that will display it.
        user_id = state.user_id or db.admin_user_id(conn)
        threshold = float(db.get_all_settings(conn, user_id)["min_match_score"])
        matched = conn.scalar(
            "SELECT COUNT(*) FROM user_jobs WHERE user_id = :user_id "
            "AND status = 'new' AND match_score >= :threshold",
            {"user_id": user_id, "threshold": threshold},
        ) if user_id is not None else 0
        error_text = state.error
        if state.source_errors:
            joined = "; ".join(f"{k}: {v}" for k, v in state.source_errors.items())
            error_text = f"{error_text}; {joined}" if error_text else joined
        conn.execute(
            """UPDATE scans SET finished_at = :now, status = :status, phase = :phase,
                   found = :found, enriched = :enriched, failed = :failed,
                   matched = :matched, error = :error, source_errors = :source_errors,
                   heartbeat_at = :now WHERE id = :id""",
            {"now": _now(), "status": state.status, "phase": state.phase,
             "found": state.found, "enriched": state.enriched, "failed": state.failed,
             "matched": matched, "error": error_text, "id": state.scan_id,
             "source_errors": json.dumps(state.source_errors) if state.source_errors
                              else None},
        )
        conn.commit()
    except Exception:
        log.exception("could not finalize scan %d", state.scan_id)

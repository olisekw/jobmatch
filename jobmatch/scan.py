"""Scan orchestrator: search enabled sources → enrich descriptions → score.

One scan at a time, run in a daemon thread owned by this module. The web
layer starts it with start_scan() and polls current_status().
"""

import json
import threading
import traceback

from playwright.sync_api import sync_playwright

import config

from . import dates, db, display, extract, salary, scoring
from .sources import SOURCES, get_enabled
from .sources.base import ScanContext

_lock = threading.Lock()
_state = None  # current/last ScanState


class ScanState:
    def __init__(self, scan_id, user_id=None):
        self.scan_id = scan_id
        self.user_id = user_id  # who asked; whose `matched` count gets recorded
        self.phase = "Starting"
        self.found = 0
        self.enriched = 0
        self.failed = 0
        self.source_errors = {}   # source name → error text
        self.status = "running"   # running | done | failed | cancelled
        self.error = None
        self.stop_requested = False
        # Naive UTC, to match what `datetime('now')` writes into `scans` — the
        # dashboard falls back across both fields and must not mix the two.
        self.started_at = display.utcnow().isoformat(timespec="seconds")

    def to_dict(self):
        return {
            "scan_id": self.scan_id,
            "status": self.status,
            "phase": self.phase,
            "found": self.found,
            "enriched": self.enriched,
            "failed": self.failed,
            "source_errors": self.source_errors,
            "error": self.error,
            "started_at": self.started_at,
        }


def current_status():
    with _lock:
        return _state.to_dict() if _state else None


def request_stop():
    with _lock:
        if _state and _state.status == "running":
            _state.stop_requested = True
            return True
    return False


def start_scan(user_id=None, trigger="manual"):
    """Start a scan thread. Returns (state dict, error message)."""
    global _state
    with _lock:
        if _state and _state.status == "running":
            return None, "A scan is already running."
        conn = db.get_conn()
        scan_id = conn.scalar(
            'INSERT INTO scans ("trigger", requested_by) '
            "VALUES (:trigger, :user_id) RETURNING id",
            {"trigger": trigger, "user_id": user_id},
        )
        conn.commit()
        conn.close()
        _state = ScanState(scan_id, user_id)
        state = _state

    thread = threading.Thread(target=_run_scan, args=(state,), daemon=True)
    thread.start()
    return state.to_dict(), None


def _run_scan(state):
    conn = db.get_conn()
    try:
        # The crawl is shared, so it runs off the admin's search settings, not
        # those of whoever pressed the button. Per-user preferences only ever
        # affect scoring, never what gets fetched.
        settings = db.get_all_settings(conn, db.admin_user_id(conn))
        sources = get_enabled(settings["enabled_sources"])
        terms = [t for t in settings["search_terms"] if str(t).strip()]
        days = int(settings["scan_days"]) or None

        ctx = ScanContext(
            progress=lambda text: setattr(state, "phase", text),
            stopped=lambda: state.stop_requested,
        )

        if any(s.needs_browser for s in sources) or _browser_enrich_pending(conn):
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
                if not state.stop_requested:
                    _enrich_phase(state, conn, page, ctx)

                browser.close()
        else:
            # API-only scan: no Playwright needed
            _search_phase(state, conn, None, sources, terms, days, ctx)
            if not state.stop_requested:
                _enrich_phase(state, conn, None, ctx)

        state.phase = "Scoring matches"
        # New jobs are new for everyone: materialize and rescore every user.
        scoring.rescore_all_users(conn)

        state.status = "cancelled" if state.stop_requested else "done"
        state.phase = "Finished"
    except Exception:
        state.status = "failed"
        state.error = traceback.format_exc(limit=3)
        state.phase = "Failed"
    finally:
        _finalize(state, conn)
        conn.close()


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
        if state.stop_requested:
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
        state.phase = f"Searching {source.label}"
        try:
            stubs = source.search(page, terms, days, known_ids, ctx)
        except Exception as e:
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
        if state.stop_requested:
            return
        source = SOURCES.get(job["source"])
        if source is None or (source.needs_browser and page is None):
            continue
        state.phase = (
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
        )
        error_text = state.error
        if state.source_errors:
            joined = "; ".join(f"{k}: {v}" for k, v in state.source_errors.items())
            error_text = f"{error_text}; {joined}" if error_text else joined
        conn.execute(
            """UPDATE scans SET finished_at = datetime('now'), status = :status,
                   found = :found, enriched = :enriched, matched = :matched,
                   error = :error, source_errors = :source_errors WHERE id = :id""",
            {"status": state.status, "found": state.found, "enriched": state.enriched,
             "matched": matched, "error": error_text, "id": state.scan_id,
             "source_errors": json.dumps(state.source_errors) if state.source_errors
                              else None},
        )
        conn.commit()
    except Exception:
        pass

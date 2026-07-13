"""Scan orchestrator: search enabled sources → enrich descriptions → score.

One scan at a time, run in a daemon thread owned by this module. The web
layer starts it with start_scan() and polls current_status().
"""

import threading
import traceback
from datetime import datetime

from playwright.sync_api import sync_playwright

import config
from . import dates, db, extract, salary, scoring
from .sources import SOURCES, get_enabled
from .sources.base import ScanContext

_lock = threading.Lock()
_state = None  # current/last ScanState


class ScanState:
    def __init__(self, scan_id):
        self.scan_id = scan_id
        self.phase = "starting"
        self.found = 0
        self.enriched = 0
        self.failed = 0
        self.source_errors = {}   # source name → error text
        self.status = "running"   # running | done | failed | cancelled
        self.error = None
        self.stop_requested = False
        self.started_at = datetime.now().isoformat(timespec="seconds")

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


def start_scan():
    """Start a scan thread. Returns (state dict, error message)."""
    global _state
    with _lock:
        if _state and _state.status == "running":
            return None, "scan already running"
        conn = db.get_conn()
        cur = conn.execute("INSERT INTO scans DEFAULT VALUES")
        conn.commit()
        scan_id = cur.lastrowid
        conn.close()
        _state = ScanState(scan_id)
        state = _state

    thread = threading.Thread(target=_run_scan, args=(state,), daemon=True)
    thread.start()
    return state.to_dict(), None


def _run_scan(state):
    conn = db.get_conn()
    try:
        settings = db.get_all_settings(conn)
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

        state.phase = "scoring"
        scoring.rescore_all(conn)

        state.status = "cancelled" if state.stop_requested else "done"
        state.phase = "finished"
    except Exception:
        state.status = "failed"
        state.error = traceback.format_exc(limit=3)
        state.phase = "failed"
    finally:
        _finalize(state, conn)
        conn.close()


def _browser_enrich_pending(conn):
    """True if jobs still needing descriptions belong to a browser source."""
    browser_sources = [n for n, s in SOURCES.items() if s.needs_browser]
    if not browser_sources:
        return False
    marks = ",".join("?" * len(browser_sources))
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM jobs WHERE TRIM(description) = '' AND source IN ({marks})",
        browser_sources,
    ).fetchone()
    return row["n"] > 0


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

    cur = conn.execute(
        """INSERT OR IGNORE INTO jobs
           (source, source_id, title, company, location, salary, freshness, link,
            description, skills, worktype, seniority, employment_type,
            posted_at, salary_min, salary_max, salary_currency, salary_period)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (source.name, stub["source_id"], stub["title"], stub["company"],
         stub["location"], stub["salary"], stub["freshness"], stub["link"],
         description, features["skills"], worktype, seniority, employment_type,
         posted_at, s_min, s_max, s_cur, s_per),
    )
    return cur.rowcount


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
                "SELECT source_id FROM jobs WHERE source = ?", (source.name,)
            )
        }
        state.phase = f"{source.label}: searching"
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
        state.phase = f"{source.label}: fetching descriptions {i}/{len(pending)}"

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
                """UPDATE jobs SET description = ?, skills = ?, worktype = ?,
                       seniority = ?, employment_type = ? WHERE id = ?""",
                (description, features["skills"], features["worktype"],
                 features["seniority"], features["employment_type"], job["id"]),
            )
            conn.commit()
            state.enriched += 1

        if not ctx.sleep(config.MIN_DETAIL_DELAY, config.MAX_DETAIL_DELAY):
            return


def _finalize(state, conn):
    try:
        settings = db.get_all_settings(conn)
        threshold = float(settings["min_match_score"])
        matched = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE status = 'new' AND match_score >= ?",
            (threshold,),
        ).fetchone()["n"]
        error_text = state.error
        if state.source_errors:
            joined = "; ".join(f"{k}: {v}" for k, v in state.source_errors.items())
            error_text = f"{error_text}; {joined}" if error_text else joined
        conn.execute(
            """UPDATE scans SET finished_at = datetime('now'), status = ?,
                   found = ?, enriched = ?, matched = ?, error = ? WHERE id = ?""",
            (state.status, state.found, state.enriched, matched,
             error_text, state.scan_id),
        )
        conn.commit()
    except Exception:
        pass

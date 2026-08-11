"""JobMatch web app.

Dev:  python3 app.py            →  http://127.0.0.1:8000
Prod: gunicorn wsgi:app         (see wsgi.py)
"""

import json
import logging
from datetime import date

from flask import Flask, g, jsonify, render_template, request, session

import config
from jobmatch import dates, db, display, resume, salary, scan, scoring
from jobmatch.sources import SOURCES

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("jobmatch")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["SECRET_KEY"] = config.SECRET_KEY


LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def check_runtime_config(deployed=None):
    """Fail loudly on config that is only safe on a local machine.

    `deployed` defaults to "bound to something other than loopback"; wsgi.py
    passes True, since running under gunicorn is deployment by definition.
    """
    if deployed is None:
        deployed = config.HOST not in LOOPBACK_HOSTS
    if deployed and config.SECRET_KEY == config.DEV_SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY is unset and the built-in dev key is only for loopback — "
            "set SECRET_KEY in the environment (see .env.example)."
        )
    if deployed and config.DEBUG:
        raise RuntimeError("JOBMATCH_DEBUG must be off when not serving on loopback.")


def bootstrap_db():
    """Create/upgrade the schema and close out scans a crash left `running`."""
    conn = db.get_conn()
    try:
        db.init_schema(conn)
        # Somebody has to own the data before Phase 3 adds real signup.
        db.ensure_local_user(conn)
        # A scan thread dies with the process; a row left `running` never finishes.
        orphaned = conn.execute(
            "UPDATE scans SET status = 'failed', finished_at = datetime('now'), "
            "error = 'interrupted by server restart' WHERE status = 'running'"
        ).rowcount
        conn.commit()
        if orphaned:
            log.warning("reconciled %d orphaned running scan(s)", orphaned)
    finally:
        conn.close()

WEIGHT_KEYS = ("weight_skill", "weight_worktype", "weight_location", "weight_seniority")
RESCORE_KEYS = WEIGHT_KEYS + (
    "user_location", "user_seniority", "user_worktype", "user_skills", "seniority_strict",
)
APPLICATION_STATUSES = db.APPLICATION_STATUSES
JOB_LIMIT = 500  # one page of results; the client says so when it bites


def get_db():
    if "db" not in g:
        g.db = db.get_conn()
    return g.db


def current_user_id():
    """The user this request acts as.

    Phase 3 replaces the body of this function with Flask-Login; it already
    reads the session so that adding a real login changes nothing else. Until
    then a single-user install has exactly one user, and every request is
    implicitly theirs.
    """
    if "user_id" not in g:
        conn = get_db()
        user_id = session.get("user_id")
        if user_id is not None and db.get_user(conn, user_id) is None:
            session.pop("user_id", None)  # session outlived the account
            user_id = None
        g.user_id = user_id if user_id is not None else db.ensure_local_user(conn)
    return g.user_id


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


# ── Pages ────────────────────────────────────────────────────

@app.route("/")
def page_dashboard():
    return render_template("dashboard.html", active="dashboard")


@app.route("/jobs")
def page_jobs():
    return render_template("jobs.html", active="jobs")


@app.route("/tracker")
def page_tracker():
    return render_template("tracker.html", active="tracker")


@app.route("/settings")
def page_settings():
    return render_template("settings.html", active="settings")


# ── Scan ─────────────────────────────────────────────────────

@app.post("/api/scan/start")
def api_scan_start():
    if not config.SCAN_ENABLED:
        return jsonify({"error": "Scanning is switched off on this instance."}), 503
    state, error = scan.start_scan(user_id=current_user_id(), trigger="manual")
    if error:
        return jsonify({"error": error}), 409
    return jsonify(state)


@app.get("/api/scan/status")
def api_scan_status():
    return jsonify(scan.current_status() or {"status": "idle"})


@app.post("/api/scan/cancel")
def api_scan_cancel():
    return jsonify({"cancelling": scan.request_stop()})


# ── Jobs ─────────────────────────────────────────────────────

@app.get("/api/jobs")
def api_jobs():
    conn = get_db()
    status = request.args.get("status", "new")
    source = request.args.get("source", "")
    q = request.args.get("q", "").strip().lower()
    sort = request.args.get("sort", "score")
    try:
        min_score = float(request.args.get("min_score"))
    except (TypeError, ValueError):
        min_score = None

    where, params = ["1=1"], {"user_id": current_user_id()}
    if status in db.JOB_STATUSES:
        where.append("uj.status = :status")
        params["status"] = status
    if source:
        where.append("j.source = :source")
        params["source"] = source
    if q:
        where.append("(LOWER(j.title) LIKE :q OR LOWER(j.company) LIKE :q)")
        params["q"] = f"%{q}%"
    if min_score is not None:
        where.append("uj.match_score IS NOT NULL AND uj.match_score >= :min_score")
        params["min_score"] = min_score

    order = ("COALESCE(j.posted_at, j.scraped_at) DESC, uj.match_score DESC" if sort == "date"
             else "uj.match_score DESC, COALESCE(j.posted_at, j.scraped_at) DESC")
    rows = conn.execute(
        f"""SELECT j.id, j.source, j.source_id, j.title, j.company, j.location,
                   j.salary, j.freshness, j.link, j.skills, j.worktype, j.seniority,
                   j.employment_type, j.scraped_at, j.posted_at, j.salary_min,
                   j.salary_max, j.salary_currency, j.salary_period,
                   uj.status, uj.match_score, uj.score_breakdown
            FROM jobs j
            JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = :user_id
            WHERE {' AND '.join(where)}
            ORDER BY {order} LIMIT {JOB_LIMIT}""",
        params,
    ).fetchall()

    jobs = []
    for row in rows:
        job = dict(row)
        job["score_breakdown"] = (
            json.loads(job["score_breakdown"]) if job["score_breakdown"] else None
        )
        job["source_label"] = getattr(SOURCES.get(job["source"]), "label", job["source"])
        job["posted_days_ago"] = dates.days_ago(job["posted_at"])
        # The client renders these as-is; `freshness` stays out of the UI because
        # it is raw board text ("pred 3 dňami") that dates.py has already parsed.
        job["posted_display"] = display.relative_date(job["posted_at"])
        job["posted_exact"] = display.exact_time(job["posted_at"])
        job["worktype_label"] = display.label(display.WORKTYPE, job["worktype"])
        job["seniority_label"] = display.label(display.SENIORITY, job["seniority"])
        job["employment_label"] = display.label(
            display.EMPLOYMENT_TYPE, job["employment_type"]
        )
        job["salary_hourly"] = salary.hourly_display(
            job["salary_min"], job["salary_max"],
            job["salary_currency"], job["salary_period"],
        )
        jobs.append(job)
    return jsonify({
        "jobs": jobs,
        "count": len(jobs),
        "truncated": len(jobs) == JOB_LIMIT,
    })


@app.post("/api/jobs/<int:job_id>/status")
def api_job_status(job_id):
    conn = get_db()
    user_id = current_user_id()
    new_status = (request.get_json(silent=True) or {}).get("status", "")
    if new_status not in db.JOB_STATUSES:
        return jsonify({"error": "A job can only be new, applied or declined."}), 400

    scope = {"user_id": user_id, "job_id": job_id}
    current = conn.scalar(
        "SELECT status FROM user_jobs WHERE user_id = :user_id AND job_id = :job_id", scope
    )
    if current is None:
        # A job scanned in since this user's last materialization has no row yet.
        if conn.scalar("SELECT id FROM jobs WHERE id = :job_id", {"job_id": job_id}) is None:
            return jsonify({"error": "That job is no longer in your list."}), 404
        db.ensure_user_jobs(conn, user_id)
        current = "new"

    conn.execute(
        "UPDATE user_jobs SET status = :status WHERE user_id = :user_id AND job_id = :job_id",
        dict(scope, status=new_status),
    )
    if new_status == "applied":
        conn.execute(
            """INSERT INTO applications (user_id, job_id, applied_at)
               VALUES (:user_id, :job_id, :applied_at)
               ON CONFLICT (user_id, job_id) DO NOTHING""",
            dict(scope, applied_at=date.today().isoformat()),
        )
    elif current == "applied":
        # Un-marking an applied job removes this user's tracker entry.
        app_id = conn.scalar(
            "SELECT id FROM applications WHERE user_id = :user_id AND job_id = :job_id", scope
        )
        if app_id is not None:
            conn.execute("DELETE FROM application_events WHERE application_id = :id",
                         {"id": app_id})
            conn.execute("DELETE FROM applications WHERE id = :id", {"id": app_id})
    conn.commit()
    return jsonify({"ok": True, "status": new_status})


# ── Applications (tracker) ───────────────────────────────────

@app.get("/api/applications")
def api_applications():
    conn = get_db()
    user_id = current_user_id()
    rows = conn.execute(
        """SELECT a.id, a.job_id, a.applied_at, a.status, a.notes,
                  j.title, j.company, j.location, j.link, j.source, uj.match_score
           FROM applications a
           JOIN jobs j ON j.id = a.job_id
           LEFT JOIN user_jobs uj ON uj.job_id = a.job_id AND uj.user_id = a.user_id
           WHERE a.user_id = :user_id
           ORDER BY a.applied_at DESC, a.id DESC""",
        {"user_id": user_id},
    ).fetchall()
    apps = []
    for row in rows:
        item = dict(row)
        item["source_label"] = getattr(SOURCES.get(item["source"]), "label", item["source"])
        item["applied_display"] = display.relative_date(item["applied_at"])
        item["applied_exact"] = display.exact_time(item["applied_at"])
        item["status_label"] = display.label(display.APPLICATION_STATUS, item["status"])
        item["events"] = [
            _event_display(dict(e)) for e in conn.execute(
                """SELECT event_at, from_status, to_status, note
                   FROM application_events WHERE application_id = :id
                   ORDER BY event_at DESC, id DESC""",
                {"id": row["id"]},
            )
        ]
        apps.append(item)
    return jsonify({"applications": apps, "count": len(apps)})


def _event_display(event):
    """Add the readable form of one status change to its row."""
    event["at_display"] = display.relative_time(event["event_at"])
    event["at_exact"] = display.exact_time(event["event_at"])
    event["from_label"] = display.label(display.APPLICATION_STATUS, event["from_status"])
    event["to_label"] = display.label(display.APPLICATION_STATUS, event["to_status"])
    return event


@app.patch("/api/applications/<int:app_id>")
def api_application_update(app_id):
    conn = get_db()
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}
    # Scoped by user_id, so another user's application id is a 404, not an edit.
    row = conn.execute(
        "SELECT id, status FROM applications WHERE id = :id AND user_id = :user_id",
        {"id": app_id, "user_id": user_id},
    ).fetchone()
    if not row:
        return jsonify({"error": "That application is no longer in your tracker."}), 404

    if "status" in payload:
        new_status = payload["status"]
        if new_status not in APPLICATION_STATUSES:
            return jsonify({"error": "That is not a status I recognize."}), 400
        if new_status != row["status"]:
            conn.execute("UPDATE applications SET status = :status WHERE id = :id",
                         {"status": new_status, "id": app_id})
            conn.execute(
                """INSERT INTO application_events
                   (user_id, application_id, from_status, to_status, note)
                   VALUES (:user_id, :id, :from_status, :to_status, :note)""",
                {"user_id": user_id, "id": app_id, "from_status": row["status"],
                 "to_status": new_status, "note": payload.get("note", "")},
            )
    if "notes" in payload:
        conn.execute("UPDATE applications SET notes = :notes WHERE id = :id",
                     {"notes": str(payload["notes"]), "id": app_id})
    conn.commit()
    return jsonify({"ok": True})


# ── Settings ─────────────────────────────────────────────────

@app.get("/api/settings")
def api_settings_get():
    conn = get_db()
    settings = db.get_all_settings(conn, current_user_id())
    settings["search_profiles"] = config.SEARCH_PROFILES
    settings["available_sources"] = {name: s.label for name, s in SOURCES.items()}
    # Labels live in one place; the pages that need a <select> or a chip read
    # them from here rather than keeping their own copy.
    settings["profile_labels"] = {
        name: display.label(display.SEARCH_PROFILE, name) for name in config.SEARCH_PROFILES
    }
    settings["application_statuses"] = [
        {"value": s, "label": display.label(display.APPLICATION_STATUS, s)}
        for s in APPLICATION_STATUSES
    ]
    settings["seniority_options"] = display.options(display.SENIORITY)
    settings["worktype_options"] = display.options(display.WORKTYPE)
    return jsonify(settings)


@app.put("/api/settings")
def api_settings_put():
    conn = get_db()
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}
    allowed = set(db.DEFAULT_SETTINGS)
    updates = {k: v for k, v in payload.items() if k in allowed}
    if not updates:
        return jsonify({"error": "There was nothing to save."}), 400

    if any(k in updates for k in WEIGHT_KEYS):
        current = db.get_all_settings(conn, user_id)
        weights = {}
        for key in WEIGHT_KEYS:
            try:
                weights[key] = float(updates.get(key, current[key]))
            except (TypeError, ValueError):
                name = display.label(display.WEIGHT, key)
                return jsonify({"error": f"{name} needs to be a number."}), 400
            if not 0 <= weights[key] <= 1:
                name = display.label(display.WEIGHT, key)
                return jsonify({"error": f"{name} needs to be between 0 and 1."}), 400
        total = sum(weights.values())
        if total <= 0:
            return jsonify({"error": "At least one weight needs to be above zero."}), 400
        for key in WEIGHT_KEYS:
            updates[key] = round(weights[key] / total, 4)

    if "min_match_score" in updates:
        try:
            updates["min_match_score"] = max(0.0, min(100.0, float(updates["min_match_score"])))
        except (TypeError, ValueError):
            return jsonify({"error": "The minimum match score needs to be a number."}), 400

    if "search_terms" in updates:
        updates["search_terms"] = [
            str(t).strip() for t in updates["search_terms"] if str(t).strip()
        ]
    if "user_skills" in updates:
        updates["user_skills"] = sorted(
            {str(t).strip().lower() for t in updates["user_skills"] if str(t).strip()}
        )
    if "enabled_sources" in updates:
        updates["enabled_sources"] = [s for s in updates["enabled_sources"] if s in SOURCES]

    db.set_settings(conn, user_id, updates)

    rescored = False
    if any(k in updates for k in RESCORE_KEYS):
        # Only this user's scores move — "matched" stays derived, and nobody
        # else's pool is touched by a weight change here.
        scoring.rescore_user(conn, user_id)
        rescored = True
    return jsonify({"ok": True, "rescored": rescored, "saved": updates})


# ── Resume upload ────────────────────────────────────────────

@app.post("/api/resume")
def api_resume():
    conn = get_db()
    user_id = current_user_id()
    file = request.files.get("resume")
    if not file or not file.filename:
        return jsonify({"error": "No file came through — try choosing it again."}), 400
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Your CV needs to be a PDF."}), 400

    # One CV per user, named by user id — never a shared path.
    pdf_path = config.resume_path(user_id)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    file.save(pdf_path)

    try:
        text = resume.pdf_to_text(pdf_path)
    except Exception:
        # The parser error is for the log; the user gets the likely cause.
        log.exception("could not read the uploaded CV at %s", pdf_path)
        return jsonify({
            "error": "That PDF could not be read — it may be password-protected or damaged."
        }), 400
    if not text.strip():
        return jsonify({
            "error": "That PDF has no text in it — it looks like a scan or a set of images."
        }), 400

    skills = resume.skills_from_text(text)
    existing = set(db.get_setting(conn, user_id, "user_skills") or [])
    merged = sorted(existing | set(skills))
    db.set_settings(conn, user_id, {"resume_text": text, "user_skills": merged})
    scoring.rescore_user(conn, user_id)

    return jsonify({
        "ok": True,
        "characters": len(text),
        "detected_skills": skills,
        "user_skills": merged,
    })


# ── Stats ────────────────────────────────────────────────────

@app.get("/api/stats")
def api_stats():
    conn = get_db()
    user_id = current_user_id()
    settings = db.get_all_settings(conn, user_id)
    threshold = float(settings["min_match_score"])
    scope = {"user_id": user_id, "threshold": threshold}

    def mine(clause):
        """COUNT over this user's slice of the shared pool."""
        return conn.scalar(
            f"SELECT COUNT(*) FROM user_jobs WHERE user_id = :user_id AND {clause}", scope
        )

    stats = {
        "threshold": threshold,
        # The pool is global; every other number below is this user's alone.
        "total_jobs": conn.scalar("SELECT COUNT(*) FROM jobs"),
        "new_jobs": mine("status = 'new'"),
        "matched": mine("status = 'new' AND match_score >= :threshold"),
        "applied": mine("status = 'applied'"),
        "declined": mine("status = 'declined'"),
        "unscored": mine("match_score IS NULL"),
        "applications_by_status": {
            row["status"]: row["n"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM applications "
                "WHERE user_id = :user_id GROUP BY status",
                {"user_id": user_id},
            )
        },
        "by_source": {
            row["source"]: row["n"]
            for row in conn.execute("SELECT source, COUNT(*) AS n FROM jobs GROUP BY source")
        },
    }
    last = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    stats["last_scan"] = _last_scan_summary(last) if last else None
    return jsonify(stats)


def _last_scan_summary(row):
    """What the dashboard is allowed to say about the last scan.

    Deliberately not `dict(row)`: `scans.error` holds a traceback, which belongs
    in the server log and never on the page. Boards that struggled are named by
    their label instead, from the structured `source_errors` column.
    """
    when = row["finished_at"] or row["started_at"]
    try:
        source_errors = json.loads(row["source_errors"]) if row["source_errors"] else {}
    except ValueError:
        source_errors = {}
    return {
        "status": row["status"],
        "status_label": display.label(display.SCAN_STATUS, row["status"]),
        "when": display.relative_time(when),
        "when_exact": display.exact_time(when),
        "found": row["found"],
        "enriched": row["enriched"],
        "matched": row["matched"],
        "problem_sources": [
            getattr(SOURCES.get(name), "label", name) for name in source_errors
        ],
    }


if __name__ == "__main__":
    check_runtime_config()
    bootstrap_db()
    log.info("serving on http://%s:%d (debug=%s)", config.HOST, config.PORT, config.DEBUG)
    # use_reloader=False: the reloader would fork a second process and orphan
    # the in-module scan thread/state.
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        use_reloader=False,
        threaded=True,
    )

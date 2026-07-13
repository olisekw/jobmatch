"""JobMatch web app.

Run: python3 app.py  →  http://127.0.0.1:8000
"""

import json
from datetime import date

from flask import Flask, g, jsonify, render_template, request

import config
from jobmatch import dates, db, resume, salary, scan, scoring
from jobmatch.sources import SOURCES

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

WEIGHT_KEYS = ("weight_skill", "weight_worktype", "weight_location", "weight_seniority")
RESCORE_KEYS = WEIGHT_KEYS + (
    "user_location", "user_seniority", "user_worktype", "user_skills", "seniority_strict",
)
APPLICATION_STATUSES = ("applied", "interview", "offer", "rejected", "withdrawn", "no_response")


def get_db():
    if "db" not in g:
        g.db = db.get_conn()
    return g.db


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
    state, error = scan.start_scan()
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

    where, params = ["1=1"], []
    if status in ("new", "applied", "declined"):
        where.append("status = ?")
        params.append(status)
    if source:
        where.append("source = ?")
        params.append(source)
    if q:
        where.append("(LOWER(title) LIKE ? OR LOWER(company) LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    if min_score is not None:
        where.append("match_score IS NOT NULL AND match_score >= ?")
        params.append(min_score)

    order = ("COALESCE(posted_at, scraped_at) DESC, match_score DESC" if sort == "date"
             else "match_score DESC, COALESCE(posted_at, scraped_at) DESC")
    rows = conn.execute(
        f"""SELECT id, source, source_id, title, company, location, salary,
                   freshness, link, skills, worktype, seniority, employment_type,
                   status, match_score, score_breakdown, scraped_at, posted_at,
                   salary_min, salary_max, salary_currency, salary_period
            FROM jobs WHERE {' AND '.join(where)}
            ORDER BY {order} LIMIT 500""",
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
        job["salary_hourly"] = salary.hourly_display(
            job["salary_min"], job["salary_max"],
            job["salary_currency"], job["salary_period"],
        )
        jobs.append(job)
    return jsonify({"jobs": jobs, "count": len(jobs)})


@app.post("/api/jobs/<int:job_id>/status")
def api_job_status(job_id):
    conn = get_db()
    new_status = (request.get_json(silent=True) or {}).get("status", "")
    if new_status not in ("new", "applied", "declined"):
        return jsonify({"error": "status must be new, applied or declined"}), 400

    job = conn.execute("SELECT id, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        return jsonify({"error": "job not found"}), 404

    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
    if new_status == "applied":
        conn.execute(
            "INSERT OR IGNORE INTO applications (job_id, applied_at) VALUES (?, ?)",
            (job_id, date.today().isoformat()),
        )
    elif job["status"] == "applied":
        # Un-marking an applied job removes its tracker entry.
        app_row = conn.execute(
            "SELECT id FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        if app_row:
            conn.execute("DELETE FROM application_events WHERE application_id = ?",
                         (app_row["id"],))
            conn.execute("DELETE FROM applications WHERE id = ?", (app_row["id"],))
    conn.commit()
    return jsonify({"ok": True, "status": new_status})


# ── Applications (tracker) ───────────────────────────────────

@app.get("/api/applications")
def api_applications():
    conn = get_db()
    rows = conn.execute(
        """SELECT a.id, a.job_id, a.applied_at, a.status, a.notes,
                  j.title, j.company, j.location, j.link, j.source, j.match_score
           FROM applications a JOIN jobs j ON j.id = a.job_id
           ORDER BY a.applied_at DESC, a.id DESC"""
    ).fetchall()
    apps = []
    for row in rows:
        item = dict(row)
        item["source_label"] = getattr(SOURCES.get(item["source"]), "label", item["source"])
        item["events"] = [
            dict(e) for e in conn.execute(
                """SELECT event_at, from_status, to_status, note
                   FROM application_events WHERE application_id = ?
                   ORDER BY event_at DESC, id DESC""",
                (row["id"],),
            )
        ]
        apps.append(item)
    return jsonify({"applications": apps, "count": len(apps)})


@app.patch("/api/applications/<int:app_id>")
def api_application_update(app_id):
    conn = get_db()
    payload = request.get_json(silent=True) or {}
    row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    if not row:
        return jsonify({"error": "application not found"}), 404

    if "status" in payload:
        new_status = payload["status"]
        if new_status not in APPLICATION_STATUSES:
            return jsonify({"error": f"status must be one of {APPLICATION_STATUSES}"}), 400
        if new_status != row["status"]:
            conn.execute("UPDATE applications SET status = ? WHERE id = ?",
                         (new_status, app_id))
            conn.execute(
                """INSERT INTO application_events
                   (application_id, from_status, to_status, note)
                   VALUES (?, ?, ?, ?)""",
                (app_id, row["status"], new_status, payload.get("note", "")),
            )
    if "notes" in payload:
        conn.execute("UPDATE applications SET notes = ? WHERE id = ?",
                     (str(payload["notes"]), app_id))
    conn.commit()
    return jsonify({"ok": True})


# ── Settings ─────────────────────────────────────────────────

@app.get("/api/settings")
def api_settings_get():
    conn = get_db()
    settings = db.get_all_settings(conn)
    settings["search_profiles"] = config.SEARCH_PROFILES
    settings["available_sources"] = {name: s.label for name, s in SOURCES.items()}
    return jsonify(settings)


@app.put("/api/settings")
def api_settings_put():
    conn = get_db()
    payload = request.get_json(silent=True) or {}
    allowed = set(db.DEFAULT_SETTINGS)
    updates = {k: v for k, v in payload.items() if k in allowed}
    if not updates:
        return jsonify({"error": "no valid settings in payload"}), 400

    if any(k in updates for k in WEIGHT_KEYS):
        current = db.get_all_settings(conn)
        weights = {}
        for key in WEIGHT_KEYS:
            try:
                weights[key] = float(updates.get(key, current[key]))
            except (TypeError, ValueError):
                return jsonify({"error": f"{key} must be a number"}), 400
            if not 0 <= weights[key] <= 1:
                return jsonify({"error": f"{key} must be between 0 and 1"}), 400
        total = sum(weights.values())
        if total <= 0:
            return jsonify({"error": "weights must not all be zero"}), 400
        for key in WEIGHT_KEYS:
            updates[key] = round(weights[key] / total, 4)

    if "min_match_score" in updates:
        try:
            updates["min_match_score"] = max(0.0, min(100.0, float(updates["min_match_score"])))
        except (TypeError, ValueError):
            return jsonify({"error": "min_match_score must be a number"}), 400

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

    db.set_settings(conn, updates)

    rescored = False
    if any(k in updates for k in RESCORE_KEYS):
        scoring.rescore_all(conn)
        rescored = True
    return jsonify({"ok": True, "rescored": rescored, "saved": updates})


# ── Resume upload ────────────────────────────────────────────

@app.post("/api/resume")
def api_resume():
    conn = get_db()
    file = request.files.get("resume")
    if not file or not file.filename:
        return jsonify({"error": "no file uploaded"}), 400
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "resume must be a PDF"}), 400

    config.DATA_DIR.mkdir(exist_ok=True)
    file.save(config.RESUME_PDF)

    try:
        text = resume.pdf_to_text(config.RESUME_PDF)
    except Exception as e:
        return jsonify({"error": f"could not read PDF: {e}"}), 400
    if not text.strip():
        return jsonify({"error": "no text found in PDF (scanned image?)"}), 400

    skills = resume.skills_from_text(text)
    existing = set(db.get_setting(conn, "user_skills") or [])
    merged = sorted(existing | set(skills))
    db.set_settings(conn, {"resume_text": text, "user_skills": merged})
    scoring.rescore_all(conn)

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
    settings = db.get_all_settings(conn)
    threshold = float(settings["min_match_score"])

    def one(sql, *params):
        return conn.execute(sql, params).fetchone()[0]

    stats = {
        "threshold": threshold,
        "total_jobs": one("SELECT COUNT(*) FROM jobs"),
        "new_jobs": one("SELECT COUNT(*) FROM jobs WHERE status = 'new'"),
        "matched": one(
            "SELECT COUNT(*) FROM jobs WHERE status = 'new' AND match_score >= ?", threshold
        ),
        "applied": one("SELECT COUNT(*) FROM jobs WHERE status = 'applied'"),
        "declined": one("SELECT COUNT(*) FROM jobs WHERE status = 'declined'"),
        "unscored": one("SELECT COUNT(*) FROM jobs WHERE match_score IS NULL"),
        "applications_by_status": {
            row["status"]: row["n"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM applications GROUP BY status"
            )
        },
        "by_source": {
            row["source"]: row["n"]
            for row in conn.execute("SELECT source, COUNT(*) AS n FROM jobs GROUP BY source")
        },
    }
    last = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    stats["last_scan"] = dict(last) if last else None
    return jsonify(stats)


if __name__ == "__main__":
    startup = db.get_conn()
    db.init_schema(startup)
    # A scan thread dies with the process; close out rows a crash/restart orphaned.
    startup.execute(
        "UPDATE scans SET status = 'failed', finished_at = datetime('now'), "
        "error = 'interrupted by server restart' WHERE status = 'running'"
    )
    startup.commit()
    startup.close()
    # use_reloader=False: the reloader would fork a second process and orphan
    # the in-module scan thread/state.
    app.run(host="127.0.0.1", port=8000, debug=True, use_reloader=False, threaded=True)

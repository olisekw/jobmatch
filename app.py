"""JobMatch web app.

Dev:  python3 app.py            →  http://127.0.0.1:8000
Prod: gunicorn wsgi:app         (see wsgi.py)
"""

import json
import logging
from datetime import date, timedelta

from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

import config
from jobmatch import auth, dates, db, display, resume, salary, scan, scoring, worker
from jobmatch.sources import SOURCES

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("jobmatch")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=config.SECRET_KEY,
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    # Session cookie policy. Lax still sends the cookie on a top-level GET, so
    # a bookmarked /jobs works, while a cross-site POST arrives without it.
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
    PERMANENT_SESSION_LIFETIME=timedelta(days=config.SESSION_DAYS),
    RATELIMIT_STORAGE_URI=config.RATELIMIT_STORAGE_URI,
    RATELIMIT_ENABLED=config.RATELIMIT_ENABLED,
)

# Every mutating route is covered by default — this app has no endpoint that
# wants to be POSTed to from elsewhere, so exemptions are opt-in and rare.
csrf = CSRFProtect(app)

limiter = Limiter(get_remote_address, app=app)

login_manager = LoginManager(app)
login_manager.login_view = "page_login"
# "strong" also pins the session to the user agent + IP hash, so a stolen
# cookie replayed from elsewhere is logged out rather than accepted.
login_manager.session_protection = "strong"


def check_runtime_config(deployed=None):
    """Fail loudly on config that is only safe on a local machine.

    `deployed` defaults to "bound to something other than loopback"; wsgi.py
    passes True, since running under gunicorn is deployment by definition.
    """
    if deployed is None:
        deployed = not config.IS_LOOPBACK
    if deployed and config.SECRET_KEY == config.DEV_SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY is unset and the built-in dev key is only for loopback — "
            "set SECRET_KEY in the environment (see .env.example)."
        )
    if deployed and config.DEBUG:
        raise RuntimeError("JOBMATCH_DEBUG must be off when not serving on loopback.")


_deployed = False


def mark_deployed():
    """Tighten what only a loopback dev server is allowed to be lax about.

    Called by `wsgi.py`, which knows something `config.py` cannot: gunicorn
    binds with `--bind` and never reads HOST, so a container would otherwise
    look like loopback and hand out session cookies without `Secure`.
    """
    global _deployed
    if _deployed:
        return
    _deployed = True

    if not config.SECURE_COOKIE_WAS_SET:
        app.config["SESSION_COOKIE_SECURE"] = True

    # Behind Caddy every request arrives from the proxy container, so without
    # this the per-IP rate limits on login and signup are one shared bucket for
    # the whole internet, and `session_protection = "strong"` pins every session
    # to the same address. Only as many hops as are actually in front of us are
    # trusted: X-Forwarded-For is client-supplied and a wrong count here lets a
    # caller pick their own IP — which is why this is off by default and is
    # never applied to the dev server, where there is no proxy at all.
    if config.TRUSTED_PROXY_HOPS > 0:
        hops = config.TRUSTED_PROXY_HOPS
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops, x_prefix=0
        )
        log.info("trusting %d proxy hop(s) for the client address", hops)


def bootstrap_db():
    """Create or upgrade the schema. Nothing else — see below.

    Reconciling scans a crash left `running` used to happen here, and can't any
    more: a web process restarting says nothing about whether a scan is running,
    because the scan is in another process entirely. That job moved to
    `jobmatch.worker`, which decides it from the heartbeat.
    """
    conn = db.get_conn()
    try:
        # No implicit local user any more: an account arrives through signup or
        # `python3 -m jobmatch.setpassword`. Creating a passwordless one here
        # would silently take the "first user is the admin" slot at signup.
        db.init_schema(conn)
        if not db.scans_accepts_queued(conn):
            # Said at boot rather than discovered by whoever first presses Scan.
            log.error(
                "this database predates the scan queue — run "
                "`python3 -m jobmatch.backfill`, or scans cannot be triggered"
            )
    finally:
        conn.close()

WEIGHT_KEYS = ("weight_skill", "weight_worktype", "weight_location", "weight_seniority")
RESCORE_KEYS = WEIGHT_KEYS + (
    "user_location", "user_seniority", "user_worktype", "user_skills", "seniority_strict",
)
APPLICATION_STATUSES = db.APPLICATION_STATUSES
JOB_LIMIT = 500  # one page of results; the client says so when it bites
PDF_MAGIC = b"%PDF-"  # every PDF starts with it; a renamed .exe does not


def get_db():
    if "db" not in g:
        g.db = db.get_conn()
    return g.db


def current_user_id():
    """The user this request acts as — always the logged-in one.

    Every route that calls this is behind `@login_required`, so `current_user`
    is guaranteed to be a real row; the assert is here to make that a loud
    failure rather than a query scoped to `user_id = None`.
    """
    assert current_user.is_authenticated, "route is missing @login_required"
    return current_user.id


@login_manager.user_loader
def load_user(user_id):
    """Session id → user row. A deleted account resolves to None and logs out."""
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    row = db.get_user(get_db(), user_id)
    return auth.User(row) if row else None


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@app.context_processor
def template_globals():
    """Instance facts the templates need. `current_user` Flask-Login adds itself."""
    return {
        "allow_signup": config.ALLOW_SIGNUP,
        "min_password_length": config.MIN_PASSWORD_LENGTH,
        # Who may trigger the shared crawl, and how often it happens anyway.
        "can_scan": config.SCAN_ENABLED and getattr(current_user, "is_admin", False),
        "scan_interval_hours": config.SCAN_INTERVAL_HOURS if config.SCAN_ENABLED else 0,
    }


# ── Auth ─────────────────────────────────────────────────────

def wants_json():
    """True for the fetch() API, false for a browser following a link."""
    return request.path.startswith("/api/")


def safe_next(target):
    """A same-site redirect target, or None.

    Only a plain absolute path is allowed: `//evil.example` and
    `https://evil.example` are both valid values of `?next=` and both leave
    this site, which is the whole open-redirect trick.
    """
    if not target or not target.startswith("/") or target.startswith("//"):
        return None
    return target


@login_manager.unauthorized_handler
def unauthorized():
    if wants_json():
        return jsonify({"error": "Your session has ended — please sign in again."}), 401
    return redirect(url_for("page_login", next=request.path))


@app.errorhandler(CSRFError)
def handle_csrf_error(err):
    """A missing or stale token is a bad request, not a traceback."""
    message = "That form or tab went stale — reload the page and try again."
    log.warning("CSRF rejected on %s %s: %s", request.method, request.path, err.description)
    if wants_json():
        return jsonify({"error": message}), 400
    flash(message)
    return redirect(request.path), 303


@app.errorhandler(413)
def handle_too_large(_err):
    message = "That file is too big — the limit is 16 MB."
    if wants_json():
        return jsonify({"error": message}), 413
    return message, 413


@app.errorhandler(429)
def handle_rate_limited(err):
    message = f"Too many attempts — try again later ({err.description})."
    if wants_json():
        return jsonify({"error": message}), 429
    flash(message)
    return render_template("auth.html", mode="login", email=""), 429


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def page_login():
    target = safe_next(request.args.get("next")) or url_for("page_dashboard")
    if current_user.is_authenticated:
        return redirect(target)

    email = ""
    if request.method == "POST":
        conn = get_db()
        email = auth.normalize_email(request.form.get("email"))
        password = request.form.get("password") or ""
        row = db.get_user_by_email(conn, email)
        if row is None:
            # Spend the same time as a real verify would, so response timing
            # does not answer "is there an account at this address?".
            auth.dummy_verify(password)
        elif auth.verify_password(row["password_hash"], password):
            _start_session(conn, row, password)
            return redirect(safe_next(request.form.get("next")) or target)
        # One message for both cases, on purpose.
        log.info("failed login for %r", email)
        flash("That email and password do not match an account.")

    return render_template("auth.html", mode="login", email=email, next=target)


@app.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def page_signup():
    if not config.ALLOW_SIGNUP:
        return render_template("auth.html", mode="closed"), 403
    if current_user.is_authenticated:
        return redirect(url_for("page_dashboard"))

    email = ""
    if request.method == "POST":
        conn = get_db()
        email = auth.normalize_email(request.form.get("email"))
        password = request.form.get("password") or ""
        problem = (
            auth.email_problem(email)
            or auth.password_problem(password)
            or (None if password == request.form.get("confirm") else "The passwords differ.")
            or (None if db.get_user_by_email(conn, email) is None
                else "There is already an account with that email.")
        )
        if problem:
            flash(problem)
        else:
            # Whoever gets there first owns the instance; on the migrated local
            # DB that slot is already taken, so signups land as regular users.
            first = db.default_user_id(conn) is None
            user_id = db.create_user(
                conn, email, auth.hash_password(password), is_admin=first
            )
            conn.commit()
            # A new account joins the shared pool with every job unscored-new.
            db.ensure_user_jobs(conn, user_id)
            log.info("created user %d (%r, admin=%s)", user_id, email, first)
            _start_session(conn, db.get_user_by_email(conn, email), password)
            return redirect(url_for("page_settings"))

    return render_template("auth.html", mode="signup", email=email)


def _start_session(conn, row, password):
    """Log `row` in and take care of what a successful login owes the account."""
    session.permanent = True
    login_user(auth.User(row))
    if auth.needs_rehash(row["password_hash"]):
        # Same password, current argon2 parameters — a login is the only moment
        # the plaintext is in hand to redo it with.
        db.set_password(conn, row["id"], auth.hash_password(password))
        log.info("rehashed password for user %d", row["id"])
    # Jobs scanned in while this user was away have no user_jobs row yet.
    db.ensure_user_jobs(conn, row["id"])


@app.post("/logout")
@login_required
def do_logout():
    logout_user()
    session.clear()
    return redirect(url_for("page_login"))


@app.post("/api/account/delete")
@login_required
@limiter.limit("5 per hour")
def api_account_delete():
    """Erase the account and everything personal attached to it.

    A CV is personal data and the whole point of a working delete, so the PDF
    goes with the rows. Deliberately irreversible: no soft-delete flag, nothing
    left behind but the shared `jobs` pool, which was never this user's.
    """
    conn = get_db()
    user_id = current_user_id()
    password = (request.get_json(silent=True) or {}).get("password") or ""
    row = db.get_user_by_email(conn, current_user.email)
    if row is None or not auth.verify_password(row["password_hash"], password):
        return jsonify({"error": "That password is not right."}), 403

    pdf_path = config.resume_path(user_id)
    try:
        pdf_path.unlink()
    except FileNotFoundError:
        pass  # never uploaded one, or already gone
    except OSError:
        # The rows still have to go; a stranded PDF is a cleanup problem, not a
        # reason to leave the account alive.
        log.exception("could not remove the CV at %s", pdf_path)

    db.delete_user(conn, user_id)
    logout_user()
    session.clear()
    log.info("deleted user %d", user_id)
    return jsonify({"ok": True, "redirect": url_for("page_login")})


# ── Pages ────────────────────────────────────────────────────

@app.route("/")
@login_required
def page_dashboard():
    return render_template("dashboard.html", active="dashboard")


@app.route("/jobs")
@login_required
def page_jobs():
    return render_template("jobs.html", active="jobs")


@app.route("/tracker")
@login_required
def page_tracker():
    return render_template("tracker.html", active="tracker")


@app.route("/settings")
@login_required
def page_settings():
    return render_template("settings.html", active="settings")


# ── Scan ─────────────────────────────────────────────────────

# One crawl serves everybody, so triggering one is an instance-wide act, not a
# personal one: regular users read the results of the schedule. This is what
# stops scraping from multiplying per user.
SCAN_NOT_YOURS = (
    "Scans run on a schedule for everyone here — only an admin can start one early."
)


@app.post("/api/scan/start")
@login_required
@limiter.limit("6 per hour")
def api_scan_start():
    # Scanning is scraping somebody else's site: the limit is about the boards,
    # not about this server.
    if not config.SCAN_ENABLED:
        return jsonify({"error": "Scanning is switched off on this instance."}), 503
    if not current_user.is_admin:
        return jsonify({"error": SCAN_NOT_YOURS}), 403
    # Queued, not started: the worker process picks it up. Which is why this
    # returns a `queued` state rather than a `running` one.
    state, error = scan.enqueue(get_db(), user_id=current_user_id(), trigger="manual")
    if error:
        return jsonify({"error": error}), 409
    return jsonify(state)


@app.get("/api/scan/status")
@login_required
def api_scan_status():
    # Read from the row, so any web worker can answer for a scan it is not
    # running — under gunicorn, most of them aren't.
    return jsonify(scan.current_status(get_db()) or {"status": "idle"})


@app.post("/api/scan/cancel")
@login_required
def api_scan_cancel():
    if not current_user.is_admin:
        return jsonify({"error": SCAN_NOT_YOURS}), 403
    return jsonify({"cancelling": scan.request_stop(get_db())})


# ── Jobs ─────────────────────────────────────────────────────

@app.get("/api/jobs")
@login_required
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

    order = db.JOB_ORDER["date" if sort == "date" else "score"]
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
def api_resume():
    conn = get_db()
    user_id = current_user_id()
    file = request.files.get("resume")
    if not file or not file.filename:
        return jsonify({"error": "No file came through — try choosing it again."}), 400
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Your CV needs to be a PDF."}), 400
    # The suffix is a claim by whoever uploaded; the header is the file itself.
    # Checked before `save()`, so a non-PDF never reaches the disk at all.
    if file.stream.read(len(PDF_MAGIC)) != PDF_MAGIC:
        return jsonify({"error": "That file is not a PDF, whatever it is named."}), 400
    file.stream.seek(0)

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
@login_required
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
    if config.SCAN_IN_PROCESS:
        # Local dev stays one command. In a deployment the worker is its own
        # container and this never runs — `wsgi.py` does not call it, because
        # every gunicorn process would start a scanner of its own.
        worker.start_thread()
    log.info("serving on http://%s:%d (debug=%s)", config.HOST, config.PORT, config.DEBUG)
    # use_reloader=False: the reloader would fork a second process, and with it
    # a second in-process scan worker.
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        use_reloader=False,
        threaded=True,
    )

<!-- Synthesized from PROJECT.md (maintain-folders pass, 2026-08-04). Edit freely — this is the plan; IDEA.md is your original idea. -->

# ROADMAP.md — JobMatch

Local single-user job scanner + scorer + application tracker. Status snapshot: 2026-08-04.

## Done
- Flask app with 4 pages (Dashboard, Jobs, Tracker, Settings) + JSON API.
- 6 working source adapters (`profesia`, `kariera`, `remoteok`, `remotive`, `jobicy`, `arbeitnow`) behind one `JobSource` interface.
- Background scan with live progress/cancel, scoring engine (re-scores instantly on weight change), regex skill/worktype/seniority extraction, salary/date parsing, PDF resume parsing, application tracking with status pipeline + event history.
- Live populated SQLite DB (~9.7MB) — actually used, not just scaffolded. Runtime settings live in the DB, editable from the UI.

## Next
- Add a test suite for scoring + extraction correctness (none exists today — relies on manual verification).
- Harden the `profesia` Playwright adapter (heaviest dependency; most likely to break silently on markup change).

## Later
- Additive new boards (new adapter file + registry entry).
- Revisit the deliberate "no FX conversion" choice if cross-currency comparison becomes annoying.

## Open questions
- Confirm the `.claude/launch.json` interpreter (`/usr/bin/python3`) matches where `requirements.txt` is installed.
<!-- The plan. Rationale lives in PROJECT.md; the original idea in IDEA.md; shipped work in CHANGELOG.md. -->

# ROADMAP.md — JobMatch

**Direction (set 2026-08-08): from local single-user tool → deployed multi-user SaaS.**

This roadmap deliberately reverses the current "single user, local machine, no auth — never
expose it to the internet" invariant in `CLAUDE.md` / `README.md`. Those docs are rewritten
as part of Phase 6, not left contradicting the code.

Realistic effort: ~6–8 focused sessions. Phase 5 is the **ship line** — a public URL exists
from that point on; everything after is improvement, not a blocker.

## Two constraints that shape everything below

1. **Scraping must not multiply per user.** Profesia.sk and Kariéra are scraped with 5–16 s
   politeness delays and no API contract. A scan per user from a cloud IP means bans and a
   ToS problem. So **the job pool stays global**: the server scans once on a schedule, and
   users get their own profile, scores, statuses and tracker on top of that shared pool.
   This is both the safe answer and the cleaner multi-tenant design.
2. **Ship before finishing.** A live URL early is worth more than an unshipped perfect system.

## Done

- Flask app, 4 pages (Dashboard, Jobs, Tracker, Settings) + JSON API.
- 6 source adapters (`profesia`, `kariera`, `remoteok`, `remotive`, `jobicy`, `arbeitnow`)
  behind one `JobSource` interface.
- Background scan with live progress/cancel; scoring engine (instant re-score on weight
  change); regex skill/worktype/seniority extraction; salary + date parsing; PDF resume
  parsing; application tracking with status pipeline and event history.
- Live, populated SQLite DB — actually used, not scaffolded. Runtime settings in the DB.
- Test suite for scoring + extraction (`tests/`, 349 lines) — **written but not yet committed.**

---

## Phase 0 — Land what already exists

No new code; untracked work that makes the repo look finished.

- Commit `tests/` (the previous roadmap still listed "add a test suite" as next — it's done).
- Commit `PROJECT.md`, `CHANGELOG.md`, this `ROADMAP.md`.
- Fill in the empty `IDEA.md` — one honest paragraph, in your own words, on the original
  itch. It reads well in a README later.
- Add `requirements-dev.txt` (`pytest`, `pytest-cov`, `ruff`).
- Branch first (`git checkout -b saas`) — never commit to `main`.

## Phase 1 — Configuration and CI

Nothing about hosting works until the app reads its environment.

- `config.py`: `DATABASE_URL`, `SECRET_KEY`, `DATA_DIR`, `DEMO_MODE`, `LOG_LEVEL`,
  `SCAN_ENABLED` from `os.environ`, with local-dev defaults. Regex/delay constants stay
  exactly where they are — the file's stated scope still holds.
- `app.py`: drop the hardcoded `debug=True` / `host="127.0.0.1"`; gate debug behind an env
  flag. Add a `wsgi.py` gunicorn entrypoint alongside the `__main__` dev runner.
- `.env.example` (`.gitignore` already covers `.env`).
- `.github/workflows/ci.yml`: `pytest` on 3.11/3.12 + `ruff check`.

## Phase 2 — Multi-tenant data model

The largest phase. Do the schema change and the DB-driver change **together, once**.

**Swap `sqlite3` for SQLAlchemy Core** (not the ORM — the existing SQL is good and readable)
in `jobmatch/db.py`, driven by `DATABASE_URL`. Dev stays on SQLite; this makes the Phase 5
Postgres switch a URL change plus a few dialect fixes instead of a second rewrite.

| Table | Change |
|---|---|
| `users` | **new** — id, email, password_hash (argon2), created_at, is_admin |
| `jobs` | **global, shared.** Drop `status`, `match_score`, `score_breakdown` — those are per-user. Keep the user-independent source/extraction fields |
| `user_jobs` | **new** — (user_id, job_id) unique; `status`, `match_score`, `score_breakdown`, `scored_at` |
| `user_settings` | replaces the global `settings` table — same key/JSON-value shape, scoped by user_id |
| `applications`, `application_events` | add `user_id`; `applications.job_id` unique becomes unique **per user** |
| `scans` | add `trigger` (schedule/manual), `requested_by` |

- `scoring.rescore_all(conn)` → `rescore_user(conn, user_id)`, writing into `user_jobs`.
  The formula and the **"score over *known* components only"** invariant are untouched —
  it survives multi-tenancy intact, and `tests/test_scoring.py` should pass with only
  signature changes.
- Materialize `user_jobs` lazily: on signup and after each scan, one `INSERT … SELECT`
  creates missing rows, then rescore. At ~10k jobs × a few users this is trivial, and it
  keeps score filtering/sorting in SQL so the `/api/jobs` query shape survives.
- CVs move from the single `config.RESUME_PDF` to `data/resumes/<user_id>.pdf`;
  `jobmatch/resume.py` is unchanged, only its caller.
- Extend `jobmatch/backfill.py` with a one-time migration creating user #1 from the existing
  local DB and reassigning all current statuses/applications to it — keeping the "additive,
  idempotent, never touch a user's data" rule.
- Every route in `app.py` gains a user scope; `get_db()` gets a `current_user()` companion.

## Phase 3 — Auth and security

- `Flask-Login` + `argon2-cffi`; signup/login/logout pages matching the existing black &
  white templates.
- CSRF on all mutating routes (`Flask-WTF`) — today `POST /api/jobs/<id>/status`,
  `PUT /api/settings` and `POST /api/resume` are wide open.
- `Flask-Limiter` on signup/login and on scan triggering.
- CV upload: verify PDF magic bytes, not just the filename suffix (the 16 MB cap exists).
- Account deletion that wipes the user's CV, settings, `user_jobs` and applications — CVs
  are personal data, and a working delete is both correct and a good interview answer.
- `SECRET_KEY` from env; secure session cookies, `SameSite=Lax`.

## Phase 4 — Get scanning out of the web process

`jobmatch/scan.py` keeps scan state in module globals (`_lock`, `_state`) — which is why the
reloader has to be disabled today. Under multiple gunicorn workers this breaks outright: a
status poll can hit a worker that knows nothing about the running scan.

- Move scan execution into a **separate worker container** running the same image.
- **Make `scans` the queue:** a trigger inserts a `queued` row; the worker claims it with a
  conditional `UPDATE … WHERE status='queued'` and writes progress back to the row.
  `current_status()` reads the DB instead of a global, so any web worker can answer.
  A small, honest SQL-backed queue — no Redis, no Celery.
- Schedule global scans (APScheduler in the worker) — e.g. every 6 h, keeping the 7-day
  incremental window and the existing politeness delays untouched.
- Manual scan becomes admin-only; regular users just see fresh jobs. This is what stops
  scraping from multiplying per user.
- Move the orphaned-`running`-scan reconciliation out of `app.py` into the worker's boot.

## Phase 5 — 🚢 SHIP LINE: containerize and deploy

**Hosting: Hetzner VPS (CX22, ~€4/mo) + Docker Compose + Caddy.** Chosen over Fly.io/Render
because the ~1 GB Playwright image and long-running scans fit an always-on box far better
than scale-to-zero PaaS; Postgres runs as a container instead of a managed-DB bill; an EU
datacenter sits closer to the Slovak boards and keeps user CVs in the EU; and "provisioned a
VPS with Docker Compose, Caddy TLS and automated Postgres backups" is a stronger CV line
than a deploy button. Trade-off: you own patching, backups and the firewall. Fly.io + Fly
Postgres is the drop-in alternative — same Dockerfile, only this phase changes.

- `Dockerfile` on `mcr.microsoft.com/playwright/python` (Chromium preinstalled): multi-stage,
  non-root, gunicorn.
- `docker-compose.yml`: `web`, `worker`, `db` (Postgres 16), `caddy` (automatic TLS).
- Provision the box: SSH keys only, ufw, unattended-upgrades, fail2ban. Domain + TLS.
- Flip `DATABASE_URL` to Postgres; fix the known dialect gaps — `datetime('now')` /
  `date('now')` schema defaults, and `INSERT OR IGNORE` in `scan.py` → `ON CONFLICT DO NOTHING`.
- Nightly `pg_dump` to a Storage Box, with a **restore actually tested once**.
- GitHub Actions deploy on green CI.

## Phase 6 — Make it presentable (the CV surface)

- **Seeded demo account**, reset nightly, linked from the landing page. Most recruiters will
  not sign up — this is what makes the URL worth putting on a CV.
- Landing page for logged-out visitors: what it does, screenshots, the scoring formula.
- Rewrite `README.md` — screenshots/GIF at the top, architecture diagram, live link, local
  quickstart. Its "Notes" section currently says don't expose this to the internet.
- Rewrite the `CLAUDE.md` single-user invariant and `PROJECT.md`'s "Why this exists".
- Structured JSON logging + Sentry free tier; `/healthz` for uptime monitoring.

## Phase 7 — Post-launch

- Harden the `profesia` Playwright adapter (heaviest dependency, most likely to break
  silently); alert when any source returns 0 results.
- Email digest of new high-scoring matches — the natural SaaS feature.
- More boards (still one file + a registry entry).
- E2E test for signup → scan → apply.
- Revisit the deliberate "no FX conversion" salary choice once users span currencies.

---

## CV framing

Bullets to grow into, each mapping to a phase above:

- Built and deployed a multi-tenant job-aggregation SaaS (Flask, Postgres, Docker Compose,
  Caddy) that scrapes 6 job boards and scores every posting against a user's CV.
- Designed a shared-crawl multi-tenant model: one scheduled scrape serves all users, with
  per-user scoring, statuses and application tracking — avoiding per-user scraping load.
- Replaced in-process background threads with a DB-backed job queue and a separate worker
  container, making the web tier horizontally scalable.
- Set up CI/CD on GitHub Actions with automated tests, image builds and zero-touch deploys.

In interviews, lead with the **scoring design** — weighted over *known* components only, so
missing data never penalises a posting, and "matched" always derived, never stored. It's the
most interesting decision in the codebase and it's genuinely yours.

## Verification checkpoints

- **Phase 2 is the risky one.** Copy the live `data/jobmatch.db` aside first; run the
  backfill against the copy and confirm every application, status and event survives as
  `user_id = 1`.
- **Phase 3:** two users, two browsers — each sees only their own tracker, and changing user
  A's weights doesn't move user B's scores.
- **Phase 4:** kill the worker mid-scan, restart, confirm the orphaned row is reconciled and
  no scan is lost or duplicated.
- **Phase 5:** restore the `pg_dump` into a scratch DB and diff row counts. A backup that has
  never been restored is not a backup.
- **Phase 6:** open the public URL on a phone; the demo account must work from a cold start.

## Open question

`.claude/launch.json` pins `/usr/bin/python3` (3.9.6); Phase 1 onward assumes 3.12. Decide
whether to bump the local interpreter or hold 3.9 compatibility in the source.

**Resolved 2026-08-08 (half of it):** `/usr/bin/python3` is 3.9.6 (Xcode) and *is* where the
deps live — `~/Library/Python/3.9/site-packages`, i.e. `pip install --user`. So `launch.json`
is correct and the app runs. The dev tools were installed the same way. Homebrew has a 3.14 at
`/opt/homebrew/bin/python3` with **no** project deps, so don't switch `launch.json` to it
without reinstalling. Still open: whether to move to a venv on 3.12 for Phase 1 (recommended —
CI targets 3.11/3.12, and pinning a Docker base image in Phase 5 makes the system Python
irrelevant anyway) or keep the source 3.9-compatible.


# Changelog — jobmatch

One line per change, newest first. The `/roadmap-task` skill appends a sentence here after
each completed roadmap task. The plan lives in `ROADMAP.md`; the rationale in `PROJECT.md`.

## 2026-08-14
- Phase 5 (containerize and deploy), everything that does not need a VPS: a multi-stage
  `Dockerfile` on Microsoft's Playwright image running non-root as one image with two
  entrypoints, a `docker-compose.yml` of `web` / `worker` / `db` (Postgres 16) / `caddy`, a
  `DEPLOY.md` runbook, `deploy/backup.sh` + `deploy/restore-check.sh`, and a `deploy.yml`
  workflow that ships on green CI. **The box does not exist yet, so there is no public URL and
  the ship line is not crossed** — what is left is a Hetzner account, a domain and four
  repository secrets, not code.
- The Postgres dialect gaps are closed and *verified against a real server*, not reasoned
  about. The `datetime('now')` / `date('now')` schema defaults became constructs with one
  rendering per dialect, chosen to keep the timestamp **string shape** identical on both
  backends so `display.py` never learns which one it is reading; sorting had to spell out
  `NULLS LAST`, since SQLite and Postgres order NULLs oppositely by default.
- CI grew two jobs: `postgres` (the 12 parity tests, which skip themselves without
  `TEST_DATABASE_URL`, plus a `wsgi` import against Postgres) and `image`, which builds the
  Dockerfile — a broken image is now a red build instead of a broken deploy.
- **Verified by running it, not by reading it.** The real Flask app booted on Postgres 16 and
  every page and JSON route was walked; the same fixture scored 300.0 on both backends and the
  queue kept its guarantees (a second enqueue is a no-op, a second claim gets nothing). The
  containers came up healthy, gunicorn served `/login`, and `setpassword` worked inside the
  image. `backup.sh` then produced a dump that `restore-check.sh` restored into a scratch
  database, matching all seven tables and `sum(match_score) = 1290.7`.
- **The restore check was then made to fail, twice** — a check that cannot fail is not a check.
  A dump missing a `jobs` row exits 3 on the foreign-key violation; a dump silently missing one
  `application_events` row exits 1 and names that row. The live database was unchanged after
  every run and the scratch database was dropped even on the failures.
- **Closed the caveat every checkpoint since Phase 2 has carried:** the live database had 0
  applications, so the application/event half of migration and restore was covered by unit
  tests only. Three applications were walked down the real pipeline through the actual routes
  (applied → interview → offer → rejected), and those rows are now what the negative control
  detects the loss of. Covered by data instead of by assumption.

## 2026-08-13
- Phase 4 (scanning out of the web process): `scans` is now the queue. A trigger inserts a
  `queued` row and returns; `python3 -m jobmatch.worker` claims it with a conditional
  `UPDATE … WHERE status = 'queued'` and writes progress, a heartbeat and the cancel flag back
  to the row. No scan state in module globals any more, so any gunicorn worker can answer a
  status poll — and `wsgi.py` is no longer single-worker-only.
- The worker also schedules the shared crawl (`SCAN_INTERVAL_HOURS`, default 6) and reconciles
  scans a dead worker left `running`. **Scheduling is a query, not a timer** — "is the newest
  scan older than the interval?" survives a restart, cannot drift and cannot double-fire, so
  there is no APScheduler dependency after all.
- Orphan reconciliation moved out of `app.bootstrap_db()`: a restarting web process says
  nothing about whether a scan is running, while a missing heartbeat says exactly that. A row
  silent for `SCAN_STALE_SECONDS` (90) is failed, which is also what stops it blocking the queue.
- Manual scans are admin-only (403 otherwise), and so is cancelling; the dashboard button and
  the overlay's cancel are rendered only for an admin, and a scheduled scan no longer throws a
  full-screen modal at a reader who never asked for one. Everyone can still watch a scan.
- `python3 app.py` runs the worker loop in a thread (`SCAN_IN_PROCESS`), so local development
  stays one command; `wsgi.py` deliberately does not, since N web processes would mean N crawlers.
- **A live database could not be queued into.** `scans` predates the `queued` status, and
  `init_schema` can add a column but not change a CHECK constraint — every enqueue failed with
  an IntegrityError. `backfill.migrate_scan_queue` rebuilds the table (create/copy/drop/rename,
  as in Phase 2), and both entrypoints now say so loudly at boot instead of letting the first
  person to press Scan find out. Found by running against a copy of the live DB, not by a test.
- Timestamps written by the queue come from Python rather than `datetime('now')`, which is one
  fewer SQLite-ism for the Phase 5 Postgres switch to fix.
- 34 new tests (152 total). Verified against a copy of the live 2375-job DB: the rebuild kept
  all 14 scan rows and the score sum of 37011.5, a real remoteok scan ran queued → claimed →
  done with its phases visible from a *second* connection, `kill -9` mid-scan was reconciled on
  restart with nothing lost or duplicated, and SIGTERM ended a running scan as `cancelled`.

## 2026-08-12
- Phase 3 (auth and security): Flask-Login sessions over argon2id hashes, with signup, login,
  logout and a `/login` redirect in front of every page and a 401 JSON body in front of every
  API route. `current_user_id()` now returns the logged-in user instead of resolving to the
  implicit local one, and `app.bootstrap_db()` no longer creates that user — an account
  arrives through signup or `jobmatch.setpassword`, and the first one created owns the
  instance as admin.
- Signup is open but env-gated by `ALLOW_SIGNUP` (default on), alongside `SESSION_DAYS`,
  `MIN_PASSWORD_LENGTH`, `SESSION_COOKIE_SECURE` and the two `RATELIMIT_*` variables. Session
  cookies are HttpOnly + SameSite=Lax, and get `Secure` automatically on a non-loopback bind.
- Added `python3 -m jobmatch.setpassword` — sets a password on an existing account or creates
  the first admin, reading the password from a prompt or `JOBMATCH_PASSWORD` rather than argv.
  This is what makes the migrated `local@jobmatch.local` account, which owns all 2375 live
  jobs, loginable: it was created with an empty `password_hash` that no argon2 verify can
  satisfy.
- CSRF (Flask-WTF) on every mutating route; `app.js` sends the token from a `<meta>` tag on
  each fetch, and a 401 now navigates to the login page instead of toasting on a dead page.
  Rate limits (Flask-Limiter) on login, signup, account deletion and scan triggering.
- CV uploads are checked for the `%PDF-` header before `save()`, so a renamed non-PDF never
  reaches the disk. Account deletion added: it verifies the password, then erases the CV file
  along with the user's `user_jobs`, settings, applications and events, leaving only the
  shared job pool.
- Login answers "no such account" and "wrong password" with one identical message, and spends
  an argon2 verify on an unknown address so response timing does not enumerate accounts.
  `?next=` only follows a same-site path.
- **`sqlalchemy` was missing from `requirements.txt`** since Phase 2 — a fresh install or CI
  run had no reason to have it. Added, along with the four auth dependencies.
- 59 new tests (118 total), including the Phase 3 checkpoint as two test clients. Verified
  against a copy of the live DB: `setpassword` made the migrated account usable with its 52
  declined / 2323 new and score sum 37011.5 intact, and a second user saving weights rescored
  only their own 2375 rows.

## 2026-08-10
- Phase 2 (multi-tenancy) verified against a copy of the live 2375-job database, which is
  what surfaced the two bugs below. All statuses and scores survived per row, the settings
  carried into `user_settings`, re-running changed nothing, and the app served every page
  and API route off the migrated DB.
- Fixed `backfill.lift_per_user_data`: SQLite cannot parse `ON CONFLICT` straight after an
  `INSERT … SELECT` — it cannot tell an upsert's `ON` from a join's — so both statements now
  carry a `WHERE true`. Postgres accepts the same clause, so it stays one statement.
- Fixed `backfill._rebuild`: `Table.to_metadata(MetaData())` cannot resolve a `ForeignKey`
  into an empty MetaData, so rebuilding `applications` failed to compile. FK targets are now
  copied in as scaffolding. `jobs` had masked this by having no foreign keys.
- Updated `tests/test_reextract.py` to the multi-tenant schema: named binds instead of `?`,
  and triage read from `user_jobs` rather than `jobs`. Added a test that one user's status
  cannot leak into another's. 59 tests, `ruff check` clean.

## 2026-08-08
- Phase 1 (config + CI): `config.py` now reads `DATABASE_URL`, `DATA_DIR`, `SECRET_KEY`,
  `JOBMATCH_DEBUG`, `HOST`/`PORT`, `LOG_LEVEL`, `SCAN_ENABLED` and `DEMO_MODE` from the
  environment, with the old local values as defaults — `python3 app.py` still needs no env.
  Added `wsgi.py` (gunicorn), `.env.example`, `pyproject.toml` (ruff + pytest) and GitHub
  Actions CI on 3.11/3.12. Startup bootstrap moved into `app.bootstrap_db()` so both
  entrypoints reconcile crash-orphaned scans; a non-loopback bind now refuses the dev
  `SECRET_KEY` or debug mode, and `POST /api/scan/start` 503s when scanning is disabled.
- First clean `ruff check`: dropped two dead imports, sorted imports across 7 files, split
  two over-long lines. No behaviour change.
- Fixed Slovak worktype/employment-type extraction: patterns matched only undeclined
  "práca z domu" and the mis-spelled "úvazok", so everyday phrasings ("ponúkame prácu
  z domu", "plný úväzok") were missed. On the current 2375-job corpus this newly parses
  employment type for 739 jobs and worktype for 131.
- Explicitly partial work-from-home ("50% práce z domu", "občasnú prácu z domu") now
  classifies as hybrid instead of fully remote, and hybrid outranks remote in priority.
  Corpus goes from remote 1354 / hybrid 30 to remote 861 / hybrid 523 — the old split
  was inflating scores, since a remote job also collects a full location score.
- Added `python3 -m jobmatch.reextract` — replays extraction over stored rows so a pattern
  fix reaches jobs already in the DB, then re-scores. Dry run by default. Adapters now
  declare `JobSource.provides` so board-supplied fields are never overwritten by regex.
  Applied to the live DB: 978 rows updated, statuses/applications untouched.
- Landed the test suite (58 tests) and the planning docs; added requirements-dev.txt.

## 2026-08-04
- Started this changelog.

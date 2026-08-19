<!-- The plan. Rationale lives in PROJECT.md; the original idea in IDEA.md; shipped work in CHANGELOG.md. -->

# ROADMAP.md — JobMatch

**Direction (set 2026-08-08): from local single-user tool → deployed multi-user SaaS.**

This roadmap deliberately reverses the old "single user, local machine, no auth — never
expose it to the internet" invariant in `CLAUDE.md` / `README.md`. Phase 3 corrected the
sentences that auth made outright false; the *presentation* rewrite — screenshots, a live
link, an architecture diagram — is still Phase 7.

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
- Test suite for scoring + extraction (59 tests) — committed.
- `jobmatch.reextract`: replays extraction over stored rows after a pattern fix (not
  originally planned; the Slovak extraction bugs made it necessary).
- Multi-tenant schema on SQLAlchemy Core, with the live DB migrated and verified (Phase 2).
- Real accounts: argon2id + Flask-Login sessions, CSRF, rate limits, account deletion, and
  `jobmatch.setpassword` for the shell (Phase 3). 118 tests.
- Scanning in its own process over a DB-backed queue, on a schedule, admin-triggered
  (Phase 4). 152 tests.
- Containerized on Postgres 16: one image, `web`/`worker`/`db`/`caddy` in Compose, nightly
  `pg_dump` with a restore check that has been run and made to fail, and a CI job per backend
  (Phase 5). 164 tests — the 12 Postgres parity tests skip themselves without a server.
  Everything but the box itself, which is an account and a domain away.

---

## Phase 0 — Land what already exists ✅ (2026-08-08)

No new code; untracked work that makes the repo look finished.

- ~~Commit `tests/`, `PROJECT.md`, `CHANGELOG.md`, this `ROADMAP.md`.~~
- ~~Add `requirements-dev.txt` (`pytest`, `pytest-cov`, `ruff`).~~
- ~~Branch first (`git checkout -b saas`).~~
- **Still open:** fill in the empty `IDEA.md` — one honest paragraph, in your own words, on
  the original itch. Nobody else can write this one; it reads well in a README later.

## Phase 1 — Configuration and CI ✅ (2026-08-08)

Nothing about hosting works until the app reads its environment.

- ~~`config.py`: `DATABASE_URL`, `SECRET_KEY`, `DATA_DIR`, `DEMO_MODE`, `LOG_LEVEL`,
  `SCAN_ENABLED` from `os.environ`, with local-dev defaults.~~ Regex/delay constants stayed
  put. `config.sqlite_path()` derives `DB_PATH` from the URL, so the Phase 2 driver swap
  has one place to change.
- ~~`app.py`: dropped the hardcoded `debug=True` / `host="127.0.0.1"`; added `wsgi.py`.~~
  Startup bootstrap (schema + orphaned-scan reconciliation) is now `app.bootstrap_db()`,
  shared by both entrypoints; `check_runtime_config()` refuses the dev `SECRET_KEY` or
  debug mode on a non-loopback bind. `POST /api/scan/start` returns 503 when
  `SCAN_ENABLED` is off.
- ~~`.env.example`~~, plus `python-dotenv` + `gunicorn` in `requirements.txt`.
- ~~`.github/workflows/ci.yml`: `pytest` on 3.11/3.12 + `ruff check`~~, and a smoke step
  importing `wsgi` under a production-shaped environment. Added `pyproject.toml` with the
  ruff/pytest config and fixed the 15 findings of the first clean run.

## Phase 2 — Multi-tenant data model ✅ (2026-08-10)

The largest phase. Do the schema change and the DB-driver change **together, once**.

~~**Swap `sqlite3` for SQLAlchemy Core**~~ — done, Core only: tables are declared as `Table`
objects so DDL is dialect-correct and `create_all` idempotent, while every *query* stays
plain `text()` SQL. The one real cost was paramstyle: `?` is a DBAPI detail psycopg2 does
not speak, so all queries moved to named `:binds`. New ids come back via `INSERT … RETURNING
id` rather than `lastrowid`, which `text()` cannot reach and Postgres does not have.

| Table | Change |
|---|---|
| `users` | **new** — id, email, password_hash (argon2), created_at, is_admin |
| `jobs` | **global, shared.** Drop `status`, `match_score`, `score_breakdown` — those are per-user. Keep the user-independent source/extraction fields |
| `user_jobs` | **new** — (user_id, job_id) unique; `status`, `match_score`, `score_breakdown`, `scored_at` |
| `user_settings` | replaces the global `settings` table — same key/JSON-value shape, scoped by user_id |
| `applications`, `application_events` | add `user_id`; `applications.job_id` unique becomes unique **per user** |
| `scans` | add `trigger` (schedule/manual), `requested_by` |

- ~~`scoring.rescore_all(conn)` → `rescore_user(conn, user_id)`, writing into `user_jobs`.~~
  Plus `rescore_all_users()`. The formula and the **"score over *known* components only"**
  invariant were untouched, and `tests/test_scoring.py` needed **no** changes at all —
  it tests `score_job` on dicts, which never learned about tenancy.
- ~~Materialize `user_jobs` lazily~~ — `db.ensure_user_jobs()`, one `INSERT … SELECT`, called
  after each scan. Score filtering/sorting stayed in SQL, so the `/api/jobs` query shape
  survived as intended.
- ~~CVs move to `data/resumes/<user_id>.pdf`~~ via `config.resume_path()`; `resume.py`
  unchanged, as predicted.
- ~~Extend `jobmatch/backfill.py` with a one-time migration~~ — `migrate_multiuser()`, which
  detects that it has already run and no-ops. SQLite cannot drop a column named in a CHECK
  constraint or widen a UNIQUE constraint in place, so `jobs`, `applications` and
  `application_events` go through the documented create/copy/drop/rename rebuild, wrapped in
  one transaction with `PRAGMA foreign_key_check` before commit.
- ~~Every route in `app.py` gains a user scope~~ — `current_user_id()` alongside `get_db()`,
  resolving to the single local user until Phase 3 puts a real login in front of it.

**Verified against a copy of the live 2375-job DB** (see checkpoints below) — this is what
the checkpoint was for, and it caught two bugs that unit tests could not have:

1. `INSERT … SELECT … ON CONFLICT` does not parse in SQLite — after a SELECT the parser
   cannot tell an upsert's `ON` from a join's, and needs a `WHERE true` to disambiguate.
   Only the two statements in `backfill.py` were affected; every other upsert uses `VALUES`.
2. `Table.to_metadata(MetaData())` cannot resolve `ForeignKey("users.id")` into an empty
   MetaData, so the rebuild of `applications` would not compile. The FK targets are now
   copied alongside it as scaffolding. `jobs` had hidden this — it has no foreign keys.

## Phase 3 — Auth and security ✅ (2026-08-12)

- ~~`Flask-Login` + `argon2-cffi`; signup/login/logout pages~~ — one `auth.html` serving all
  three modes, standalone rather than extending `base.html` (there is no nav to show somebody
  who is not signed in). `jobmatch/auth.py` holds hashing, the credential rules and the
  Flask-Login `User`, and imports no routing — `setpassword` and the tests both need it
  without the web app. `current_user_id()` is now `current_user.id` behind an assert, and
  `bootstrap_db()` **stopped** creating the implicit local user: a passwordless account
  created at startup would silently take the "first user is the admin" slot at signup.
- ~~**Signup is open but env-gated**~~ — `ALLOW_SIGNUP`, plus `SESSION_DAYS`,
  `MIN_PASSWORD_LENGTH`, `SESSION_COOKIE_SECURE` and `RATELIMIT_*`, all in `config.py` and
  `.env.example`. Length is the only password rule; composition rules buy "Password1!".
- ~~**`python3 -m jobmatch.setpassword`**~~ — password from a prompt or `JOBMATCH_PASSWORD`,
  never argv, where `ps` and the shell history would both keep it. Creates the first admin on
  an empty DB and materializes `user_jobs` for a new account, so its Jobs page is not empty
  until the next scan.
- ~~CSRF on all mutating routes~~ — `CSRFProtect` app-wide, with `app.js` reading the token
  from a `<meta>` tag and sending `X-CSRFToken` on every non-GET fetch. Two handlers keep the
  two clients apart: a `CSRFError` and a 401 answer JSON to `/api/*` and a flash + redirect to
  a browser. A 401 in `api()` now navigates to `/login`, since a toast on a page that can no
  longer load anything is not an error message.
- ~~`Flask-Limiter` on signup/login and on scan triggering~~, plus account deletion. Storage
  is in-memory and per-process, which is honest for one gunicorn worker; `RATELIMIT_STORAGE_URI`
  is where Phase 5 points it at redis if there is ever more than one.
- ~~CV upload: verify PDF magic bytes~~ — checked *before* `save()`, so a renamed non-PDF
  never reaches the disk at all.
- ~~Account deletion~~ — password-confirmed, wipes the CV file with the rows, irreversible by
  design (no soft-delete flag). The shared `jobs` pool stays; it was never the user's.
- ~~`SECRET_KEY` from env; secure session cookies, `SameSite=Lax`~~ — and `Secure` follows the
  bind rather than being hardcoded, since it would make the cookie invisible over the plain
  http local dev serves. `session_protection = "strong"`. One trap worth remembering for
  Phase 5: gunicorn binds with `--bind` and never reads `HOST`, so a container looks exactly
  like loopback to `config.py`. `wsgi.py` calls `app.mark_deployed()` for that, which is also
  the right hook for anything else only a deployed process should tighten.
- Not asked for, but the phase is about credentials so it belongs: login answers "no such
  account" and "wrong password" **identically**, and spends an argon2 verify on an unknown
  address (`auth.dummy_verify`) so response timing cannot enumerate accounts either. `?next=`
  only follows a same-site path — `//evil.example` is a valid value and leaves the site.

**Found on the way:** `sqlalchemy` was never added to `requirements.txt` in Phase 2, so CI and
any fresh install had no reason to have it. Fixed here with the four auth dependencies.

## Phase 4 — Get scanning out of the web process ✅ (2026-08-13)

- ~~Move scan execution into a separate worker~~ — `jobmatch/worker.py`, run as
  `python3 -m jobmatch.worker`. It is also the local dev path: `python3 app.py` starts the
  same loop in a thread (`SCAN_IN_PROCESS`), so one command still works, while `wsgi.py`
  deliberately does not — every gunicorn process would otherwise start a crawler.
- ~~**Make `scans` the queue**~~ — with four new columns (`phase`, `heartbeat_at`,
  `claimed_by`, `cancel_requested`) plus `failed`, which live progress had always shown but
  never stored. The claim is `UPDATE … WHERE id = (SELECT … LIMIT 1) AND status = 'queued'`:
  the second worker re-checks the status after the first one's write lands and matches no
  rows. `enqueue` guards the same way from the other side — `INSERT … SELECT … WHERE NOT
  EXISTS` rather than a SELECT and then an INSERT. No Redis, no Celery, as planned.
- ~~Schedule global scans~~ — but **without APScheduler**. Scheduling is a query, not a timer:
  "is the newest scan older than `SCAN_INTERVAL_HOURS`?" survives a restart, cannot drift and
  cannot double-fire if a second worker ever exists. Same reasoning that made `scans` the
  queue; the dependency bought nothing.
- ~~Manual scan becomes admin-only~~ — 403 for everyone else, on cancel as well as start. The
  UI follows: the dashboard button and the overlay's cancel button are only rendered for an
  admin, and a *scheduled* scan no longer opens the full-screen overlay on a reader who never
  asked for one (it still refreshes their lists when it finishes). Phase 6 will demote that
  overlay for everybody.
- ~~Move orphan reconciliation into the worker's boot~~ — and give it a rule rather than an
  assumption. A restarting web process says nothing about whether a scan is running; a missing
  heartbeat says exactly that. Rows silent for `SCAN_STALE_SECONDS` are failed, at boot and on
  every idle pass, which is also what stops a dead scan from blocking the queue for ever.
  Failed rather than requeued: an interrupted scan loses nothing, but a crash-inducing scan
  that requeued itself would loop.

**Found on the way — and only by running against the live database:** `scans` was created
before `queued` was a status, and `init_schema` can add a *column* to a live table but not
change a CHECK constraint. Every enqueue on the real DB failed with an IntegrityError while
all 34 new tests passed on their freshly-created schemas. `backfill.migrate_scan_queue` now
rebuilds the table with the Phase 2 create/copy/drop/rename dance, and `db.scans_accepts_queued`
is checked at boot by both entrypoints, so an un-migrated database is a loud log line rather
than a 500 for whoever presses Scan first.

## Phase 5 — 🚢 SHIP LINE: containerize and deploy 🟡 (built and verified 2026-08-14; not yet on a box)

**Everything that can be verified without a VPS is done and was actually run.** What is left
is not code: a Hetzner account, a domain, and the four GitHub secrets. Until those exist there
is no public URL, so the ship line is **not** crossed — see "Remaining" below.

**Hosting: Hetzner VPS (CX22, ~€4/mo) + Docker Compose + Caddy.** Chosen over Fly.io/Render
because the ~1 GB Playwright image and long-running scans fit an always-on box far better
than scale-to-zero PaaS; Postgres runs as a container instead of a managed-DB bill; an EU
datacenter sits closer to the Slovak boards and keeps user CVs in the EU; and "provisioned a
VPS with Docker Compose, Caddy TLS and automated Postgres backups" is a stronger CV line
than a deploy button. Trade-off: you own patching, backups and the firewall. Fly.io + Fly
Postgres is the drop-in alternative — same Dockerfile, only this phase changes.

- ~~`Dockerfile` on `mcr.microsoft.com/playwright/python` (Chromium preinstalled): multi-stage,
  non-root, gunicorn.~~ One image, two entrypoints — the worker is the same code with a
  different command, and a second image would be a second thing to keep in step. It is 3.8 GB
  before our code and deleting the unused Firefox/WebKit saves nothing, because they live in a
  base layer that a later `rm` only hides. `PLAYWRIGHT_VERSION` pins the image tag and the pip
  package together; they disagree and Chromium is "not found".
- ~~`docker-compose.yml`: `web`, `worker`, `db` (Postgres 16), `caddy` (automatic TLS).~~
  `db`+`web`+`worker` were brought up and verified (below). **`caddy` is the one service still
  unexercised** — it needs a real domain to complete an ACME challenge, so it cannot be tested
  locally and is verified on the box or not at all.
- **Still open:** provision the box (SSH keys only, ufw, unattended-upgrades, fail2ban) and
  point a domain at it. Written up step by step in `DEPLOY.md §1`; needs an account, not code.
- ~~Flip `DATABASE_URL` to Postgres; fix the known dialect gaps.~~ The `datetime('now')` /
  `date('now')` schema defaults are now dialect-rendered constructs (`to_char(now() AT TIME
  ZONE 'utc', …)` on Postgres) that keep the *string shape* identical across backends, which is
  what lets `display.py` read either one. `backfill.py` stays SQLite-only by design. Sorting
  needed `NULLS LAST` spelled out, since the two dialects order NULLs oppositely by default.
- ~~Nightly `pg_dump` to a Storage Box, with a **restore actually tested once**.~~ `deploy/backup.sh`
  + `deploy/restore-check.sh`; run for real, including two negative controls (below).
- ~~GitHub Actions deploy on green CI.~~ `.github/workflows/deploy.yml` written, and CI grew a
  `postgres` job (parity tests + a Postgres import smoke) and an `image` job that builds the
  Dockerfile — a broken image is now a red build rather than a broken deploy. The deploy job
  itself cannot run until the box and its four secrets exist.

**Verified 2026-08-14, locally, against real Postgres 16 and the real containers:**

1. **The dialect gaps are closed.** `tests/test_postgres.py` — the 12 tests that skip
   themselves without `TEST_DATABASE_URL` — pass against `postgres:16`. Then the more useful
   check, because the rest of the suite is SQLite-only *by construction*: the actual Flask app
   booted on Postgres and every page and JSON route was walked (all four pages, `/api/jobs` with
   each filter and sort, stats, settings, applications, the queue). The same fixture scored
   **300.0 on both backends**, and `enqueue`/`claim_next` kept their guarantees — a second
   enqueue is a no-op, a second claim gets nothing.
2. **The image runs.** `db` + `web` + `worker` came up healthy on `--wait`; gunicorn served
   `/login`, the worker logged `polling every 5s`, `setpassword` created an account inside the
   container, and all four pages returned 200 from the containerized app.
3. **The backup restores — and the check can fail.** `backup.sh` produced a 36 K dump and a CV
   archive; `restore-check.sh` restored it into a scratch database and matched **every** table
   plus `sum(match_score) = 1290.7`. Then two negative controls, because a check that cannot
   fail is not a check: a dump with a `jobs` row removed exits **3** (the FK violation trips
   `ON_ERROR_STOP`), and a dump silently missing one `application_events` row exits **1** with
   `← MISMATCH` on exactly that row. The live database was byte-identical after all five runs
   and the scratch database was dropped every time.

**Found on the way — the Phase 2/3 caveat is finally closed.** Every checkpoint since Phase 2
carried the same footnote: the live DB has **0 applications**, so the application/event half was
covered by unit tests only. Three applications were walked down the real pipeline
(applied → interview → offer → rejected) through the actual routes, giving 3 `applications` and
4 `application_events` rows — which then round-tripped through `pg_dump` and are what negative
control (3) detects the loss of. That half is now covered by data, not by assumption.

**Remaining before the ship line is crossed** — none of it code:

- A Hetzner box + a domain, per `DEPLOY.md §1–2`.
- `caddy` and TLS, which only a real domain can exercise.
- The four repository secrets in `DEPLOY.md §6`, which is what arms `deploy.yml`.
- Point `REMOTE_TARGET` at a Storage Box — `backup.sh` warns loudly while it is unset, and a
  backup that only exists on the box is not a backup if the box is what dies.

## Phase 6 — Make the UI worth showing

Everything works and nothing looks finished. This sits **before** the CV surface on purpose:
Phase 7's screenshots, landing page and demo account are only worth having once the pages
behind them are worth looking at.

**Schedule-independent.** Every item below touches only `templates/`, `static/css/style.css`
and `static/js/app.js` — no schema, no new dependency, nothing that Phases 3–5 can break. The
one exception is the job detail view, which needs a route. So this phase can be pulled forward
at any time, in whole or one bullet at a time.

- **Stop the scan overlay hijacking the page.** `#scan-overlay` is a full-screen modal over an
  operation that takes *minutes* — the Slovak scrapers sleep 5–16 s between requests by design,
  and that delay is deliberate and staying. Demote it to a dismissible progress strip in the
  nav so the user can keep triaging while a scan runs. `scanOverlay`'s polling already carries
  phase and counts; only the presentation changes.
- **A job detail view.** `jobs.description` is scraped, stored and then never shown — today the
  only way to read a posting is to leave the app for the board. Needs a page route plus
  `GET /api/jobs/<id>`; the one item here that isn't pure front-end.
- **Make the score readable.** `.score` prints a bare number and hides the per-component
  breakdown in a `title=` tooltip (`breakdownTitle` in `app.js`), which touch devices never
  see. Show the four components as a bar — and keep "not known" visually distinct from zero,
  because the whole point of scoring over *known* components is that missing data is not a
  penalty. This is the most interesting thing the app does; the UI should say so.
- **Real loading and error states.** Loading is currently the literal string `Loading…` in an
  `.empty` div, and *every* error is a 3.5 s toast — including the three Settings save buttons,
  where the message belongs beside the field it's about. Skeleton rows, a pending state while a
  filter change is in flight, inline form errors.
- **Mobile.** `tracker.html` is a six-column `<table>` with no reflow whatsoever; the `.job`
  grid only half-collapses at the 720 px breakpoint. Cards below the breakpoint for both.
- **Dark mode.** `:root` already defines `--ink` / `--paper` / `--gray-*`, so a
  `prefers-color-scheme` block is a token swap rather than a rewrite. Cheap, and it's the first
  thing anyone opening the demo at night will notice.
- **Accessibility and keyboard.** Tabs and preset chips are `<button>`s with no `aria-pressed`;
  the scan overlay is not a dialog (no focus trap, no Esc); `#toast` is not `aria-live`; there
  is no `:focus-visible` styling outside inputs. Then the power feature this layout is already
  asking for: `j`/`k` between jobs, `a`/`d` to apply or decline.
- **Small ones.** The dashboard fetches `/api/stats` twice on load (`loadStats` and
  `loadTopJobs`); the `JOB_LIMIT = 500` truncation is a sentence of prose with no paging behind
  it; there is no favicon.

## Phase 7 — Make it presentable (the CV surface)

- **Seeded demo account**, reset nightly, linked from the landing page. Most recruiters will
  not sign up — this is what makes the URL worth putting on a CV.
- Landing page for logged-out visitors: what it does, screenshots, the scoring formula.
- Rewrite `README.md` — screenshots/GIF at the top, architecture diagram, live link, local
  quickstart. Its "Notes" section currently says don't expose this to the internet.
- Rewrite the `CLAUDE.md` single-user invariant and `PROJECT.md`'s "Why this exists".
- Structured JSON logging + Sentry free tier; `/healthz` for uptime monitoring.

## Phase 8 — Post-launch

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

- ~~**Phase 2 is the risky one.**~~ **Done 2026-08-10.** Ran against a `.backup()` copy of the
  live DB under `DATA_DIR=<scratch>` (which isolates the CV move too — `move_resume` renames
  the real `data/cv.pdf` otherwise). All 2375 rows kept their status *and* score **per row**,
  not merely in aggregate: 52 declined / 2323 new, score sum 37011.5, all 15 settings keys
  carried into `user_settings`, every `user_jobs` row owned by `user_id = 1`. Re-running twice
  more changed nothing. Then the app booted against the migrated DB and all four pages plus
  the JSON API returned 200.
  **Caveat:** the live DB has **0 applications and 0 events**, so the application/event half
  of this checkpoint is only covered by `_rebuild`'s `defaults={"user_id": …}` path and the
  unit tests — not by real data. Worth re-checking once the tracker has rows in it.
- ~~**Phase 3:** two users, two browsers.~~ **Done 2026-08-12.** Run twice: as
  `TenantIsolationTests` (two Flask test clients), and by hand against a `.backup()` copy of
  the live DB. There, `setpassword` made `local@jobmatch.local` loginable with its 52 declined
  / 2323 new and score sum **37011.5** intact — the same numbers the Phase 2 checkpoint
  recorded — while a second account got its own 2375 `user_jobs` rows and, on saving weights,
  rescored to 16824.9 without moving user A by a single point. Statuses, trackers, settings
  and stats are all scoped; another user's application id is a 404, not an edit.
  **Caveat, inherited:** still 0 applications in the live DB, so the tracker half of the
  isolation check is covered by the unit tests only.
- ~~**Phase 4:** kill the worker mid-scan, restart, confirm the orphaned row is reconciled and
  no scan is lost or duplicated.~~ **Done 2026-08-13**, against a `.backup()` copy of the live
  DB and, for the kill itself, a scratch DB with a deliberately slow fake board:
  1. `backfill` rebuilt `scans` keeping all 14 rows, 2375 jobs and the score sum of 37011.5;
     re-running says "already accepts queued rows".
  2. A real Remote OK scan went queued → claimed → running → done (33 new jobs), with phases
     and counts read the whole time from a **second connection** — the poll path that used to
     require being the process that started the scan.
  3. `kill -9` mid-scan left `running` at "page 5"; the queue correctly refused a new scan
     until the restart reconciled the row to `failed`, after which one could be queued again.
     Two scan rows total: nothing lost, nothing duplicated.
  4. `SIGTERM` (a `docker compose stop`) ended the running scan as `cancelled` with a
     `finished_at`, in under half a second, and the process exited on its own.
  5. Cancel from another process — what the button does — was picked up by the scan within one
     heartbeat, with `cancelling: true` visible to pollers in between.
- ~~**Phase 5:** restore the `pg_dump` into a scratch DB and diff row counts. A backup that has
  never been restored is not a backup.~~ **Done 2026-08-14**, against the real compose stack on
  Postgres 16:
  1. `backup.sh` → a 36 K gzipped dump + a CV archive (the CVs live in a volume, not in
     Postgres, so they are a separate half of the backup and were checked to contain the file).
  2. `restore-check.sh` restored it into `jobmatch_restore_check` and matched all seven tables
     — users 2, jobs 33, user_jobs 66, user_settings 5, **applications 3, application_events 4**,
     scans 1 — plus `sum(match_score) = 1290.7`. Exit 0.
  3. **The check was then made to fail, twice.** A dump missing a `jobs` row exits 3 on the FK
     violation; a dump silently missing one `application_events` row exits 1 and points at that
     row. "RESTORE OK" therefore means something.
  4. The live database was unchanged after all five runs, and the scratch database was dropped
     each time — including on the runs that failed.

  **Not covered:** `caddy`, TLS and `deploy.yml`, all three of which need a real domain and box.
- **Phase 6:** start a scan and keep triaging jobs while it runs; open all four pages at 375 px
  wide; get through Jobs and Settings on the keyboard alone; look at both colour schemes.
- **Phase 7:** open the public URL on a phone; the demo account must work from a cold start.

## Open question

`.claude/launch.json` pins `/usr/bin/python3` (3.9.6); Phase 1 onward assumes 3.12. Decide
whether to bump the local interpreter or hold 3.9 compatibility in the source.

**Resolved 2026-08-08 (half of it):** `/usr/bin/python3` is 3.9.6 (Xcode) and *is* where the
deps live — `~/Library/Python/3.9/site-packages`, i.e. `pip install --user`. So `launch.json`
is correct and the app runs. The dev tools were installed the same way. Homebrew has a 3.14 at
`/opt/homebrew/bin/python3` with **no** project deps, so don't switch `launch.json` to it
without reinstalling. Still open: whether to move to a venv on 3.12 (recommended — CI targets
3.11/3.12, and pinning a Docker base image in Phase 5 makes the system Python irrelevant
anyway) or keep the source 3.9-compatible.

**Phase 1 held both:** CI runs 3.11/3.12 while `pyproject.toml` pins ruff's `target-version`
to `py39`, so lint never rewrites the source past what the local interpreter runs. That costs
nothing today and stops being a question the moment there's a venv or a Docker base image —
but decide before Phase 2, because SQLAlchemy is the point where the split gets expensive.

**Closed 2026-08-10 — the split never got expensive.** Phase 2 went in on 3.9.6 with
SQLAlchemy 2.0.51 (installed `--user`) and the suite is green on it; nothing in Core needed
3.10+ syntax. So the answer is "keep holding both, and let Phase 5 end it": the Docker base
image pins the real runtime, at which point the system Python stops mattering and the `py39`
ruff target can be raised in the same commit. No venv needed in between.


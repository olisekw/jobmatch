<!-- The plan. Rationale lives in PROJECT.md; the original idea in IDEA.md; shipped work in CHANGELOG.md. -->

# ROADMAP.md — JobMatch

**Direction (set 2026-08-08): from local single-user tool → deployed multi-user SaaS.**

This roadmap deliberately reverses the old "single user, local machine, no auth — never
expose it to the internet" invariant in `CLAUDE.md` / `README.md`. Phase 3 corrected the
sentences that auth made outright false; Phase 7 did the presentation rewrite — screenshots,
an architecture diagram, and a "Notes" section that no longer tells you to keep it off the
internet. The one thing still missing from it is the live link, because the box does not exist.

Realistic effort: ~6–8 focused sessions. Phase 5 is the **ship line** — a public URL exists
from that point on; everything after is improvement, not a blocker. **Phase 9 is what
crosses it**: Phase 5 built and verified everything that can be verified without a VPS, so
what remains is an account, a domain, and the checks only a real host can answer.

## Two constraints that shape everything below

1. **Scraping must not multiply per user.** Profesia.sk and Kariéra are scraped with 5–16 s
   politeness delays and no API contract. A scan per user from a cloud IP means bans and a
   ToS problem. So **the job pool stays global**: the server scans once on a schedule, and
   users get their own profile, scores, statuses and tracker on top of that shared pool.
   This is both the safe answer and the cleaner multi-tenant design.
2. **Ship before finishing.** A live URL early is worth more than an unshipped perfect system.

## Done

- Flask app, 4 pages (Dashboard, Jobs, Tracker, Settings) + JSON API.
- 7 source adapters (`profesia`, `kariera`, `jobscz`, `remoteok`, `remotive`, `jobicy`,
  `arbeitnow`) behind one `JobSource` interface.
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
- A UI that can be shown to somebody: scan progress demoted from a modal to a strip, a job
  detail page, the score's four components drawn as bars with "not known" distinct from zero,
  skeleton/pending/error states, cards on a phone, dark mode, keyboard triage, and real paging
  (Phase 6). 176 tests.
- A front door: a public landing page with the scoring formula and screenshots in both colour
  schemes, a seeded demo account anybody can click into and actually use (reset nightly by the
  worker), `/healthz`, JSON logging and optional Sentry (Phase 7). 216 tests.
- Boards that can no longer be quietly broken (`ctx.seen()` — "nothing new" and "nothing at
  all" stopped looking the same), a hardened profesia adapter, and the whole loop covered end
  to end through the real routes and the real worker (Phase 8, first two items). 230 tests.
- The email digest: the worker mails each user their new matches, once per job, on a schedule
  that is a query — off entirely unless the instance has an SMTP host (Phase 8). 264 tests.
- Remote jobs scored on where they actually hire: `user_regions` ("where you can work"),
  derived from the user's town when unanswered, expanded once in `places.reachable_codes()`
  and read by the scorer, the Jobs filter and the digest alike (Phase 8). 318 tests.
- The shared crawl narrowed to where its users can work: `ctx.regions`, the union of every
  account's reach, and a real `geo` on the one board that takes one (Phase 8). 340 tests.
- A posting hiring in five places stored as five: `jobs.countries` next to the printed
  `jobs.country`, one derivation behind both, with the scorer and the filter asking the set
  (Phase 8). 369 tests, and 19 jobs a European could not previously see in the live pool.
- A seventh board and two refusals: `jobscz` brings the Czech market and CZK, while
  `nofluffjobs` and `startup.jobs` were verified unreachable politely and left unbuilt
  (Phase 8). 417 tests.
- Two salaries compared on one period **and** one currency: `salary.hourly_eur()` over an
  approximate, dated euro table that nothing stored reads, ending a "Best pay" list whose
  entire top five was Czech (Phase 8). 433 tests.

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

## Phase 6 — Make the UI worth showing ✅ (2026-08-20)

Everything worked and nothing looked finished. This sat **before** the CV surface on purpose:
Phase 7's screenshots, landing page and demo account are only worth having once the pages
behind them are worth looking at. All of it shipped in one pass — no new dependency, no schema
change, and the only route added is the job detail view.

- ~~**Stop the scan overlay hijacking the page.**~~ `#scan-overlay` is now `#scan-strip`, a
  sticky bar under the nav with the phase, the counts, the admin's cancel and a dismiss. A
  scan takes *minutes* by design — the Slovak scrapers sleep 5–16 s between requests and that
  is staying — so the page underneath stays usable and triage continues while it runs. Dismiss
  is **per scan**, keyed on `scan_id` in `sessionStorage`: hiding this one does not hide the
  next. `scanOverlay` became `scanStrip`; the polling it already did was untouched, as planned
  — only the presentation changed.
- ~~**A job detail view.**~~ `/jobs/<id>` + `GET /api/jobs/<id>`. `jobs.description` was
  scraped, stored and never shown, so reading a posting meant leaving for the board. The list
  and the detail now share one `_job_payload()` — a job cannot word itself two ways depending
  on which page shows it — and the description stays **out** of the list payload, where it
  would be ~4 KB × 50 rows. A job with no `user_jobs` row yet (scanned in after signup) is
  materialized rather than 404'd; a genuinely unknown id is a 404.
- ~~**Make the score readable.**~~ The four components were hidden in a `title=` tooltip that
  touch devices never see. They are now bars: a compact four-bar stack on every row, and a
  labelled panel with percentages when the score is clicked (`aria-expanded`, so it is a real
  disclosure and works on a phone and from the keyboard). **"Not known" is a hatched track,
  never an empty bar** — the whole point of scoring over *known* components is that missing
  data is not a penalty, and the UI now says so instead of hiding it.
- ~~**Real loading and error states.**~~ Skeleton rows in the shape of the list that is
  coming; a filter change dims the current list rather than blanking the page (`.pending`), so
  moving a slider no longer makes the page jump; a failed load gets a message and a **Try
  again** button; and the three Settings save buttons report beside themselves — an error
  stays until it is fixed, a success fades. `prefers-reduced-motion` turns the pulses off.
- ~~**Mobile.**~~ Both lists become cards under 720 px. The tracker's six-column table
  reflows with every cell carrying its own label via `data-label` + `::before` — using flex,
  not grid, because a cell with two children (a title and its ↗) put the second one on a row
  of its own. `[hidden] { display: none !important }` had to go in globally: turning table
  parts into blocks otherwise resurrects everything the app hid.
- ~~**Dark mode.**~~ A token swap, as predicted — with one correction. Swapping `--ink` and
  `--paper` turns the black nav bar into a **white slab** at night, so the chrome got its own
  `--surface` / `--on-surface` tokens while everything else kept reading `--ink`/`--paper` and
  needed no new rule. `color-scheme: light dark` makes the form controls follow.
- ~~**Accessibility and keyboard.**~~ `aria-pressed` on the tabs and preset chips, an
  `aria-live` toast, a skip link, `aria-current` in the nav, labels on the tracker's inputs,
  `:focus-visible` rings everywhere. Then the power feature: `j`/`k` between jobs, `a`/`d` to
  apply or decline, `s` for the breakdown, `Enter` to open, `/` to search, `Esc` to leave a
  field. The cursor survives a re-render and never steals focus back from the search box.
- ~~**Small ones.**~~ The dashboard asks `/api/stats` **once** (it was fetched by both
  `loadStats` and `loadTopJobs`); `JOB_LIMIT` has real paging behind it — `/api/jobs` takes
  `limit`/`offset` and answers with `total`/`has_more`, the client pages 50 at a time with
  "Load more", and `limit` is clamped so one caller cannot ask for the whole table; and there
  is a favicon (an SVG that inverts itself for a dark browser chrome).

**Found on the way:** the shared `jobCard()` renderer is the reason the dashboard and the Jobs
page cannot drift apart again — they had already duplicated the row markup twice, and the
score bars would have been a third copy. It is also what made `actions: false, skills: false`
on the dashboard a parameter rather than a second template.

## Phase 7 — Make it presentable (the CV surface) ✅ (2026-08-24)

Everything worked, was deployable and had nothing at the front of it. No schema change and one
new runtime dependency (`sentry-sdk`, inert without a DSN). Three new routes: `/` for a
stranger, `POST /demo`, and `/healthz`.

- ~~**Seeded demo account**, reset nightly, linked from the landing page.~~ `jobmatch/demo.py`
  plus `python3 -m jobmatch.demo`. The decision worth recording is that it is **not
  read-only**: a demo where the sliders do not move and nothing can be triaged is a screenshot,
  so a visitor gets a real account they can re-weight and triage — which is safe *because* the
  reset undoes it. Three holes are punched in it instead: no CV upload (a public PDF drop box,
  and the seeded skills are the point), no self-deletion, and never an admin, which is what
  stops it triggering the shared crawl without a special case in the scan route.
  Identified by email against `config.DEMO_EMAIL`, so `users` needed no column and no
  migration. The account **keeps its id and its hash across a reset** — wiping the row would
  sign out whoever is reading the page at 03:00 — so `db.delete_user` was split, and
  `db.reset_user_data` is the half the reset uses.
- ~~Reset nightly~~ — **by the worker, as a query, not a timer**, exactly like the scan
  schedule: "is `demo_reset_at` older than `DEMO_RESET_HOURS`?" The marker is a `user_settings`
  row, which is safe next to real settings because `api_settings_put` only writes keys that are
  in `DEFAULT_SETTINGS` — a visitor cannot postpone their own reset. Wrapped in the worker so a
  broken demo can never stop the thing that scrapes.
- ~~Landing page for logged-out visitors.~~ `/` branches on `current_user.is_authenticated`
  rather than becoming two routes: `/` is the URL that gets shared and bookmarked, and sending
  a stranger from it to a login form is how a public instance reads as a private tool. The page
  is standalone (like `auth.html`) and has no script tag at all. It leads with the scoring
  formula, because that is the most interesting thing in the codebase.
- ~~Screenshots~~ — `tools/screenshots.py`, Playwright against a `.backup()` copy of the live
  2375-job DB with the demo seeded into the *copy*, served by the real `python3 app.py`. Taken
  in **both colour schemes** and shipped as `<picture>` with a `prefers-color-scheme` source,
  on the landing page and in the README: the app has a dark mode, and advertising it with
  light-only screenshots misrepresents it. Regenerating them is one command, so they can stop
  being a chore that rots.
- ~~Rewrite `README.md`~~ — screenshots at the top, a mermaid architecture diagram, the
  deployment, the demo, and the "don't expose this to the internet" note replaced with what is
  actually true: it expects to be deployed, refuses its dev key off loopback, and wants the
  bundled Caddy in front. ~~`CLAUDE.md`~~ and ~~`PROJECT.md`~~ likewise. There is still no
  public URL, so the live link is an honest "not yet, and here is what it is waiting for".
- ~~Structured JSON logging + Sentry; `/healthz`.~~ `jobmatch/obs.py`, shared by both
  entrypoints so `web` and `worker` cannot describe themselves differently — `LOG_FORMAT=json`
  and `JOBMATCH_COMPONENT` are set per container, `extra={...}` becomes queryable fields, and a
  line raised inside a request carries `method`, `path` and `user_id` (never the email).
  `setup_logging` *replaces* the root handlers rather than calling `basicConfig`, which no-ops
  the moment any import has added one. Sentry is off without a DSN and tolerates not being
  installed at all: a crash reporter must never be what stops the app booting.
  `/healthz` is public, runs a real `SELECT 1` and answers 503 when it fails — the failure it
  exists to catch is the web container up while Postgres is not, which `/login` (the old
  compose healthcheck) answers 200 to quite happily.

**Found on the way — a Phase 6 defect the phone checkpoint caught.** The nav overflowed the
viewport at 390 px: four uppercase labels plus the sign-out button measured 554 px, so *every*
page scrolled sideways. Phase 6 had fixed the sign-out wrapping onto two lines and missed the
overflow behind it, because a full-page screenshot of a page that scrolls horizontally still
looks fine — which is the lesson: measure `scrollWidth`, do not look at a picture. The nav is
now allowed to be two lines on a phone, the brand keeping the first and the links and sign-out
sharing the second.

**Also found:** "the first account is the admin" was written as `default_user_id(conn) is None`,
i.e. "is the table empty?". A seeded demo account is a user and is deliberately *not* an admin,
so on a fresh box it would have taken the slot and left the instance with no owner at all. It
is now `db.has_admin(conn)` — the question that sentence always meant — in both signup and
`setpassword`.

## Phase 8 — Post-launch ✅ (2026-08-29)

Every item below is closed. With it, **the only unfinished work left in this roadmap is
Phase 5's "Remaining before the ship line is crossed" — and none of it is code**: a Hetzner
box, a domain, the repository secrets, and a `REMOTE_TARGET` for the backups. Until
those exist there is no public URL, and several verification checkpoints (TLS, `caddy`,
`deploy.yml`, a real mail relay, and whether the silent-board alarm is right about profesia's
live markup) stay honestly uncovered. A new phase should be planned **after** that, so it is
planned against a deployed thing rather than an imagined one.

**Phase 9 (planned 2026-08-29) is that deployment and nothing else** — the work Phase 5 left
behind plus the checkpoints earlier phases recorded as "needs the box", with post-launch
features held in its `## Later` bucket until there is a deployed thing to plan them against.
It found two things this paragraph had wrong: the secrets are six, not four, and Phases 7
and 8 are not in the repository at all.

- ~~Harden the `profesia` Playwright adapter (heaviest dependency, most likely to break
  silently); alert when any source returns 0 results.~~ **Done 2026-08-24.** The failure this
  is about raises nothing: an adapter whose selectors stopped matching parses no offers,
  returns no stubs and finishes green — which is precisely what an incremental scan with
  nothing new to find also looks like. So adapters now report what the board **showed** them,
  before any filtering (`ctx.seen(n)`), and the orchestrator accuses a source of returning
  "no listings at all" only when that number is zero. It is logged at ERROR, so Sentry makes
  an event of it, and it lands on the scan row, so the dashboard names the board — while the
  scan itself still finishes `done`, because a silent board is a warning about the board and
  not a failed crawl. A cancelled scan never accuses anybody: we stopped it, it did not fail.
  Profesia specifically: a timeout now retries and, if it still fails, is *reported* rather
  than ending that term's search indistinguishably from "no results"; pagination is capped at
  `MAX_PAGES` instead of trusting the site's own end-of-results signal; the first page is
  fetched once rather than twice (the old loop went to the search URL and then immediately
  back to it as page 1, with no politeness delay in between); and a row whose title link
  moved counts as *unread*, not as a listing, so a half-redesign still trips the alarm.
  Two things fell out of it: the enrich phase counts an empty description as a failed read
  (only the raising half was ever counted, so a detail selector that quietly stopped matching
  reported zero failures), and `has_detail_page = False` on the four feed boards stops it
  asking them for a description their listing already carried.
- ~~Email digest of new high-scoring matches — the natural SaaS feature.~~ **Done
  2026-08-24.** `jobmatch/digest.py` (what goes in one, and when) over `jobmatch/mail.py`
  (SMTP, and nothing about jobs) — split for the same reason `obs.py` is split from the
  entrypoints. One new column, no new dependency, no new route. The decisions worth keeping:
  **what goes in one is not a second opinion.** It selects on exactly the clause the dashboard
  counts "matched" with — `status = 'new'` and `match_score >= min_match_score` — plus
  `digested_at IS NULL`. One derivation, so the email and the Jobs page cannot disagree.
  **A job is emailed once, and that is stored rather than derived.** `user_jobs.digested_at`
  is a fact about the send, because it has to be: a posting that crosses the threshold only
  when the user moves a weight *is* news to them, and no comparison against `scraped_at`
  would ever notice it. Jobs that did not fit stay unmarked and lead the next digest, so the
  first one against a 783-match backlog is a top-10 rather than a data dump.
  **A broken relay costs latency, not matches.** The run is stamped *before* the send — a
  mail server refusing connections is retried tomorrow, not every ten seconds — and the jobs
  only after it, so a failure loses nothing. Each send is wrapped, so one bounced address
  cannot stop the others.
  **Scheduling is a query, not a timer** — the third thing built that way after the scan
  schedule and the demo reset. **And it is off unless the instance can actually send mail**:
  no `SMTP_HOST` (or no `MAIL_FROM`, which every relay demands) and the worker skips the
  pass, Settings says so, and nothing else changes — the shape `SENTRY_DSN` already had. Mail
  is never a startup dependency. Per-account switch under Notifications; the demo account is
  excluded outright, since its address is published on the landing page and its nightly reset
  would hand it the same matches every day. `python3 -m jobmatch.digest` has `--status`,
  `--dry-run` and `--user … --force`.
- **Look outside Slovakia: EU-remote as a first-class target.** The pool leans Slovak because
  two of the six boards only ever list Slovak jobs and the other four were added for volume
  rather than for reach. Three separate gaps, worth doing in this order:
  - ~~**Scoring says every remote job fits, and it does not.**~~ **Done 2026-08-27.** It is
    now a rule over a column that already existed: remote is judged on `jobs.country` against
    the set of places the user can work in, on-site and hybrid still on the town. The three
    decisions worth keeping:
    **Remote is a work permit and on-site is a commute**, which is why one component carries
    two rules rather than being split in two — it is still one question ("can this person
    take this job, where it is?") and the weight slider in Settings still means one thing.
    Prague is in Europe and is still not a commute from Bratislava, so the region rule
    deliberately does *not* leak into the non-remote branch.
    **The preference is not `user_location`** — `user_regions`, a set of `places` codes, for
    exactly the reason written below: "where I can legally work" and "where I live" are
    different questions. But it is **derived when unanswered** rather than defaulted, from
    the user's town: their country plus whatever region contains it. So the setting can sit
    empty (and Settings can say it is following the town) while scoring still has something
    honest, and a Canadian starts at Canada + North America rather than at Europe.
    **One expansion, read by everything that has an opinion about where.**
    `places.reachable_codes()` runs both ways — a region covers the countries inside it, a
    country is covered by a posting addressed to its whole region, a worldwide posting
    reaches everybody — and the scorer, the Jobs filter (`country=reachable`, offered as
    *Somewhere I can work*) and, through the score, the digest all read it, so the list and
    the score cannot disagree. Nothing answered expands to nothing, which the filter ignores
    rather than obeys — an empty `IN ()` would have emptied the page, and "a filter value the
    server does not recognise is ignored rather than obeyed" is already the rule there.
    Not done, and deliberately: `backfill.py` does not rescore. It promises never to touch a
    user's scores, and it does not have to — every scan already calls `rescore_all_users`,
    and any Settings save rescores that user immediately.
  - ~~**Ask the boards for Europe instead of filtering their answer.**~~ **Done 2026-08-28.**
    Adapters get `ctx.regions` — on the context rather than in `search`'s signature, because
    it is a fact about the run and not a new argument every board has to accept, which also
    keeps "adding a board = one file implementing `search(page, terms, days, known_ids, ctx)`"
    literally true. Three decisions worth keeping:
    **Where is the one crawl setting that is not the admin's.** The terms, the boards and the
    window are theirs because the pool is shared; *where* cannot be, for the same reason —
    their answer is not the other accounts'. `db.crawl_regions` is the union of every
    account's reach through the same `db.user_regions` the scorer reads, and **one user
    nobody can place empties it**, back to asking for everything. A narrowed crawl never
    fetches what it did not ask for, and the pool is the only place a score can come from,
    so the failure mode of guessing is a job that account was owed and will never see.
    **One geo or none.** Only `jobicy` can be asked (`&geo=<slug>`, confirmed live: an
    unknown slug is a 400, and a region still returns the worldwide postings, so narrowing
    loses nothing the scorer would have kept — asking for `python` in Europe dropped the
    Mexico-only roles and kept every "Anywhere" one). But the board rate-limits — 429 after
    fifteen quick requests — so `places.covering_region()` returns the *one* region that
    covers everybody or None, and a crawl spanning two regions asks for everything rather
    than crawling the same board twice per term. Narrowing is allowed to be an optimisation,
    never a second pass.
    **An unconfirmed narrowing is worse than none.** Remotive and Arbeitnow accept unknown
    query parameters and answer as if they were absent — `&geo=europe` on Remotive returns
    character-for-character the same jobs — so a `geo` guessed at from a plausible API shape
    would have looked like it worked and quietly done nothing. Both adapters now say in their
    docstring that they send no geography and why; Remote OK takes no parameters at all.
    **Still open, and this is where the reach actually is:** `remoteok` and `remotive` cannot
    be narrowed at all, which leaves the third bullet below carrying the EU-remote goal.
  - ~~**More EU-remote boards**~~ **Done 2026-08-29.** Three were named; **one shipped**,
    and the other two were not built on purpose. `jobmatch/sources/jobscz.py` + a registry
    entry, plus the two places a board is easy to add without: `db.DEFAULT_SETTINGS`
    (on by default) and `places.SOURCE_DEFAULT` (`jobscz` → CZ, so an unplaceable Czech
    town is still Czech). It brings the Czech market, a second currency into the pool and
    the seventh board. Four decisions worth keeping:
    **The two that were dropped were dropped on their own robots.txt, not on effort.**
    `nofluffjobs` renders nothing without JavaScript (its own page says so) and serves the
    listings from `/api/`, with `/posting/` — the detail pages, bare and under every one of
    its seven language prefixes — disallowed too: the only polite way in is a door the site has closed.
    `startup.jobs` answers **403 to everything but robots.txt**, its feed included. Both
    verified live rather than assumed. A board we can only reach by ignoring what it asked
    for is not reach, and half-writing either adapter would have left the refusal
    undiscoverable in a file nobody opens.
    **A window this board does not understand is not an error, it is the whole board.**
    `date=` honours exactly `24h`, `3d` and `7d` (282 results → 23, 74, 139); `1d`, `2d`,
    `4d`, `14d`, `30d`, `1m`, `1w` and a nonsense `99z` all returned the full 282,
    character for character — the Remotive failure mode the bullet above is about. So
    `_date_step` only ever sends one of the three that were *watched* to move the count,
    and asks for everything when the user's window is wider than a week.
    **An ad's expiry sits in the same element as its posting date.** "Končí za 3 dny" is a
    deadline and "Přidáno včera" is a birthday; reading the first as the second dates a job
    by its own death. The Czech relative and year-less absolute forms ("před 3 dny",
    "24. srpna") went into `dates.py` next to the Slovak ones rather than into the adapter.
    **One link, two boards.** Every card links to `www.jobs.cz/rpd/<id>/`, which 302s
    either to jobs.cz's own server-rendered ad view *or* to the employer's microsite,
    whose body is fetched client-side by a widget. Measured over 30 live ads across two
    terms: **21 hosted, 9 microsite** — so plain HTTP alone reads about seven ads in ten,
    and those other three would have landed unscored *and* been re-fetched by every later
    scan forever, since `_enrich_phase` selects on an empty description and a row it can
    never fill is a politeness delay paid every time. `fetch_detail` therefore tries plain
    HTTP first and renders only what that misses, telling the two pages apart by which
    selector answers rather than by parsing a redirect target we do not control. Two costs
    accepted openly: `needs_browser = True` is declared for the *detail* pages although
    `search` never touches the page, because "sometimes" is worse than "yes" — otherwise
    whether a Czech job gets scored would depend on whether profesia happened to be enabled
    — and the widget's own GraphQL endpoint was left alone, being the same kind of door
    `nofluffjobs` was just refused for. The one thing that had to be *measured* rather than
    designed: the widget mounts its container empty and fills it a moment later, so waiting
    on the element alone returned an **11-character skeleton** against real bodies of
    2 800–6 000 — which would have stored as a successful read of a job that then scores on
    nothing and is never retried. A body too short to be a posting is treated as not-yet-
    there and finally as a failed read: one more scan, against losing the job.
    The first *full* live scan then found the second thing: the microsites come in at least
    **two templates**, hanging the ad on different ids, and three of thirty ads were on the
    other one. The fix is the class both templates build on (`.cp-detail`, measured identical
    to whichever id applies across six unrelated employers) rather than a list of ids that
    grows by one every time a scan is run — 30 found, **27 enriched, 3 failed** before it,
    30/30 after.
    **And the board it landed on found an invariant that was only true by accident.**
    "A source's structured fields beat regex extraction" held everywhere except the enrich
    phase, which overwrote `worktype`/`seniority`/`employment_type` from the description
    unconditionally — because until `jobscz` no board had *both* a `provides` declaration
    and a detail page (every earlier one that stated a field is a feed board, and feed
    boards never walk that phase). So the first live scan quietly erased a `hybrid` the
    board had printed on its own card, replacing it with the None its prose implied.
    `_enrich_phase` now skips the columns a source declares, reading the same `provides`
    that `reextract` already trusts for exactly this reason.
  - ~~**A posting hiring in five places is stored as one of them, and it is not always the
    right one.**~~ **Done 2026-08-28.** `places.country` was first-match-wins over a single
    free-text field, so Remotive's "LATAM, Europe, USA, Canada, APAC" was stored `US` and
    "Americas, Europe, Israel" `IL` — both then *unreachable* for a European, though both
    say Europe out loud. The choice was between the **most inclusive** match and a **set**,
    and it went to the set, because the most inclusive one is still one answer and a posting
    naming two disjoint regions would stay wrong for somebody. Four decisions worth keeping:
    **Reach is a question about a set, and the printed place is a different question.**
    `jobs.countries` holds every code the text names (`|EU|US|CA|`, delimited on both ends
    so `|US|` cannot match inside another code — `NA` is a substring of `LATAM`);
    `jobs.country` holds the one a card prints. They are **one derivation** — `places.codes()`
    then `places.primary()` — so the column the filter selects on and the word the chip shows
    cannot become second opinions of each other, which is the failure the old single column
    actually was.
    **Which one prints is decided by `covering_region`, not by "the first".** If the places
    all sit inside one region the specific one is honest ("Berlin, Germany — Europe" is a
    German job); if they do not, the widest wins, because naming one of five reads as the
    *only* one. The chip then says "Europe +4" and names the other four on hover — server-side,
    like every other label a card shows, since "+4" with nothing behind it is a worse chip
    than the wrong one was.
    **A row is right the moment the column exists, not the moment somebody backfills.**
    `places.COUNTRIES_SQL` and its Python mirror `places.stored_codes` fall back to the single
    code, so the window between `init_schema` adding the column and `backfill` filling it is
    not a window where every remote job scores unknown. `backfill.migrate_countries` then packs
    old rows — and is the one backfill that *rewrites* a column, because two columns out of step
    is the bug rather than a migration of it — while `jobmatch.reextract` replays placement over
    all rows after a table fix, next to the extraction replay it already did.
    **Verified against the live pool, not against fixtures.** Rehearsed on a copy of the real
    2 375-row database (which predates `jobs.country` entirely, so it exercised the whole
    migration): 2 229 rows placed, **85 name more than one place**, 24 print a different
    country under the new rule, and **19 are jobs a European can now reach that were
    invisible before** — including both strings quoted above, which are really in there.
    It also surfaced a table gap the set made visible: Remotive writes "northern america",
    which matched nothing.

  ~~**The preference this needs is not `user_location`.**~~ **Shipped with the first item,
  2026-08-27** — `user_regions`, plus the derivation in `db.user_regions` and the expansion in
  `places.reachable_codes`. One deviation from the plan as written: `ANY` is not in the
  default set, because worldwide-hiring postings reaching everybody is a rule inside the
  expansion rather than something each user has to have picked — and `ANY` *in* a preference
  has to keep meaning "I can genuinely work anywhere", which is the answer the two remaining
  items must not accidentally give everybody back.
- ~~E2E test for signup → scan → apply.~~ **Done 2026-08-24.** `tests/test_e2e.py`, and the
  two rules it keeps are what make it worth having next to 225 unit tests: **CSRF stays on**
  and the token is carried the way the pages carry it (the hidden field for the login and
  signup forms, the `<meta>` tag that `app.js` reads for every fetch), and **the scan is run
  by `worker.run(once=True)`** on the worker's own connection — the entrypoint the container
  starts — never by calling into `scan` from inside a request. The web tier only enqueues, so
  a test that scanned in the request would be exercising a path production does not have; it
  asserts that too, by checking `jobs` is still empty between the queue and the worker pass.
  The board is a fake in the `SOURCES` registry with two offers written so the score is an
  assertion rather than a shrug — one is everything the profile asks for and scores 100 on
  all four components, the other is none of it and scores 0 — and it is deliberately a
  *detail-page* board, because that is profesia's shape and the only one that walks the
  enrich phase. Also covered end to end: a second scan of an unchanged board is a quiet
  success that re-reads no descriptions, a user who signs up *after* the crawl gets the
  shared pool ranked for themselves without moving anyone else's, and a regular user asking
  for a scan gets a 403 while a request with no token gets a 400 — with nothing queued either
  time.
- ~~Revisit the deliberate "no FX conversion" salary choice once users span currencies.~~
  **Done 2026-08-29.** It stopped being anticipated the moment `jobscz` put CZK in the pool
  next to EUR, and the live database says how badly: **the entire top five of "Best pay" was
  Czech**, a 120 000 Kč month reading as 750 an hour and outranking a $220k American salary,
  purely because koruna has more digits. `salary.hourly_eur()` and its SQL mirror
  `HOURLY_EUR_SQL` now put every posting on one period **and** one currency. Four decisions
  worth keeping:
  **The app already had an FX table; it was hiding under another name.** `_MAGNITUDE_SCALE`
  — `{CZK: 25, PLN: 4.3}`, added last session so a bare "70 000 Kč" would be read as a month
  and not a year — is an approximate rate to the euro and nothing else. A second table beside
  it would have been two opinions about one fact, so there is one, `EUR_RATES`, and both
  questions ask it: *what unit is this number in* and *what is it worth*. They are the same
  question about a currency — how big a number in it is.
  **Nothing stored is converted, and that is what makes an approximate rate honest.**
  The amount, the currency and the period go into `jobs` exactly as the board wrote them, and
  `range_display` still reads them back in the board's own money; the euro figure is derived
  on the way out. So refreshing the rates rewrites no row, needs no backfill and cannot move a
  score — it moves a ranking and an "≈" on a card. That is also why the rate ships with the
  date it was read (ECB reference rates of 2026-08-28, cross-checked against a second provider
  to within 0.3 %) and why the card carries the sentence saying what it was converted at: a
  rate quoted without its date is claiming to be current, and this one is a constant in a
  source file.
  **A currency with no rate is unknown, never par.** It returns NULL, so it sorts last and
  fails a floor — the same shape an unknown *period* already had, and the same shape a posting
  that quotes nothing has. Reading it at par would print a euro figure for a wage nobody
  quoted in euros, which is a wrong answer rather than a missing one. `pay=listed` still keeps
  it, because that filter asks a different question: whether the board named a figure at all.
  **The floor had to learn a currency, so the label became the server's.** "50+ an hour" was
  read in each job's own money — honest only while the pool was euros and dollars, and a
  40 000 Kč month (about €10 an hour) cleared it. The floors are euros now, so `/api/settings`
  hands over `{value, label}` pairs like it already does for countries, and the page prints
  "€50+ an hour" rather than wording the currency itself.
  **Rehearsed against the real 2 375-job database**, read-only, and it moved exactly what it
  should: 1 680 postings quote a comparable salary, **41 change rate** (15 CZK, 26 USD) and
  none becomes uncomparable. "≥ 50/h" drops from 47 jobs to 20 — the 15 Czech ones never paid
  it, and 12 dollar salaries sat in the 14 % the euro rate takes off. The new top of "Best
  pay" is $120–170/h and $220k, which is what the sort was always meant to say.
  PLN, GBP and CHF have rates but no jobs yet: the two boards that would have brought PLN and
  GBP are the two refused above.
  **Found on the way, and left alone:** the single highest-paid posting in the pool, before
  and after, is a Slovak "it junior" at "1 286 - 1 739 eur/hod." — the employer typed a monthly
  range and an hourly unit. Our parse is faithful to the ad, which is the invariant, and no
  currency rule can fix an ad that lies about its own period.

## Phase 9 — 🚢 Cross the ship line (planned 2026-08-29, not started)

Phase 8 asked that the next phase be planned **after** deployment, "against a deployed thing
rather than an imagined one". This phase does not break that rule: it is *the deployment*, not
the features that come after it. Nothing here invents a capability — every item is either the
work Phase 5 left behind, or a check that some earlier phase recorded as "not covered, needs
the box". Post-launch ideas stay in `## Later` below, unplanned on purpose.

Two things found while planning it, both of which change what this phase has to contain:

- **The last two phases are not in the repository.** `main`, `origin/saas` and the working
  branch `phase6-ui` all point at the same commit (`6b62e1f`), and 62 files are uncommitted —
  which is Phase 7 and Phase 8 in their entirety: `landing.html`, `job.html`, `digest.py`,
  `mail.py`, `obs.py`, `places.py`, `demo.py`, `sources/jobscz.py`, the FX salary work and ten
  test files. `deploy.yml` deploys the commit CI went green on, on `main`. So the pipeline as
  it stands would put a JobMatch on the box with no landing page, no demo, no digest, no
  places, no Czech board and no currency conversion — and until then a laptop's working tree
  is the only copy of a third of this project.
- **It is six repository secrets, not four.** Phase 5 and Phase 8 both say "the four
  repository secrets in `DEPLOY.md §6`"; §6 lists six and `deploy.yml` reads all six —
  `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PATH`, `DEPLOY_SSH_KEY`, `DEPLOY_HOST_KEY`,
  `DEPLOY_DOMAIN`. Four of them armed is a workflow that fails at the step after the one you
  were watching.

Items 1 and 3 need no box and should go first; 2 needs no box either and is worth doing
*before* one exists, because Let's Encrypt rate-limits failure. Everything from 4 down is
gated on an account and a domain, which is Oliver's to buy and nobody else's.

- [ ] **1. Get Phase 7 and Phase 8 into `main`.** Review the 62 changed files, commit them on
  a branch, and merge — the ordinary flow, but it is the first item in this phase because
  every later one deploys whatever `main` holds, and because a green suite in an uncommitted
  tree protects nothing. Check `.gitignore` still excludes the database, `data/` and `.env`,
  and check no CV or scraped row rides along. `origin/saas` and `phase6-ui` both sitting on
  the old commit is worth resolving at the same time rather than leaving three names for one
  thing. **Verify:** `git status` clean, `origin/main` at the new commit, the `test`,
  `postgres` and `image` jobs of `ci.yml` all green on it — the image job in particular, since
  nothing has built the Dockerfile since `jobscz` added a Playwright path to a *detail* fetch.
- [ ] **2. Exercise `caddy` without a domain.** Phase 5 recorded that `caddy` "cannot be tested
  locally and is verified on the box or not at all". That is true only of the ACME challenge.
  Caddy has its own local CA (`tls internal`) and Let's Encrypt has a staging endpoint
  (`acme_ca`), and between them everything in `deploy/Caddyfile` except the real challenge can
  be run on a laptop against a hosts-file name. **Verify:** an HTTPS handshake to the stack
  through `caddy`; all four headers present on a real page (HSTS, `nosniff`, `DENY`,
  `same-origin`) and `Server` absent; a >20 MB upload rejected by the proxy rather than by
  Flask; the automatic `http://` → `https://` redirect confirmed rather than assumed, since
  the Caddyfile does not write one; and — the one that actually matters for correctness —
  `X-Real-IP`/`X-Forwarded-For` arriving such that Flask-Limiter counts the client and not the
  `caddy` container, which is a rate limit that either works or silently protects nothing.
- [ ] **3. Correct `PROJECT.md`, which today's work made wrong.** It says six source adapters
  (seven), 318 tests (433), and carries **"No FX conversion for salary"** as a key decision —
  reversed outright this morning. A stale count is untidy; a reversed decision left standing
  as a decision is the kind of staleness that misleads, and `PROJECT.md` is the file that
  exists to say *why*. Its "Known rough edges" also still describes a Phase 5 that this phase
  is about to close. **Verify:** every claim in "Current state" re-read against the tree, not
  against the roadmap.
- [ ] **4. [Oliver] Buy the box and the domain.** Hetzner CX22 in an EU datacenter, and a
  domain with an A record (and AAAA if the box gets a v6). `DEPLOY.md §1–2` has it step by
  step: SSH keys only, `ufw`, unattended-upgrades, `fail2ban`, a `deploy` user, Docker.
  **Verify:** `ssh deploy@host docker compose version` answers, the domain resolves to the
  box from off the network, and password SSH is refused.
- [ ] **5. First boot, and the first certificate.** `.env` from `.env.example` — `SECRET_KEY`
  from `secrets.token_hex(32)` and not the dev key, `POSTGRES_PASSWORD`, `DOMAIN`,
  `ACME_EMAIL`, `PUBLIC_BASE_URL` — then `docker compose up -d --build --wait`, then
  `setpassword` for the first admin. Point `acme_ca` at staging for the first issuance and
  only then take it off, so a Caddyfile mistake costs a staging cert and not a week of the
  real rate limit. **Verify:** `https://$DOMAIN/healthz` returns `{"status": "ok"}` over a
  publicly-trusted certificate; all six pages load; the session cookie carries `Secure`
  (which is `mark_deployed()` doing its job through gunicorn, the one path `wsgi.py` exists
  for); and `SSLLabs`/`curl -I` shows HSTS on the real host.
- [ ] **6. Arm the pipeline — all six secrets.** `DEPLOY.md §6`, corrected to six.
  **Verify:** an empty commit on `main` goes green in CI, triggers `deploy.yml`, and the
  workflow's own `https://$DOMAIN/login` smoke test passes — and then a deliberately broken
  container makes the workflow *fail* rather than quietly serve a 502, because a deploy check
  that cannot fail is not a check (the same standard `restore-check.sh` was held to).
- [ ] **7. A backup that survives the box.** Order a Hetzner Storage Box, set `REMOTE_TARGET`,
  and put `backup.sh` on a nightly cron. `backup.sh` warns while it is unset, and it is right
  to: a backup that only exists on the box is not a backup if the box is what dies.
  **Verify:** `backup.sh` stops warning; then `restore-check.sh` run on the box against a dump
  **pulled back from the Storage Box**, not the local copy — exit 0, all seven tables and the
  `sum(match_score)` matched. The local-copy restore is already proven; the remote round trip
  is the half that has not been.
- [ ] **8. The first scheduled scan — which is the silent-board alarm's first real test.**
  Phase 8 built the alarm and said plainly what was still unproven: `ctx.seen()` counts what
  the parser found in *fixture* HTML, so whether the counts are right about profesia's and
  kariéra's live markup is unknown. One scheduled crawl on the box settles it, and it settles
  the Playwright-in-a-container question at the same time. **Verify:** a scan reaches `done`;
  every enabled board reports a non-zero seen count; if one reports zero, the alarm has worked
  and that adapter's selectors are the next task, not a bug in the alarm. Watch memory against
  the worker's 1500m limit while Chromium is up.
- [ ] **9. A real mail relay.** `DEPLOY.md §7` — a transactional relay, never the box itself.
  **Verify:** `digest --status`, then `--dry-run`, then one real `--force` send to a real
  inbox; it arrives, it is **not** in spam, and SPF and DKIM both show `pass` in the received
  headers. That is the half a socket on 127.0.0.1 could never cover.
- [ ] **10. The live link.** `README.md`, `landing.html` and `PROJECT.md` all currently say
  there is no box; the CV bullets below say "built and deployed" and are one sentence short of
  true. **Verify:** the URL in the README opens the landing page on a phone off wifi; one tap
  on the demo button signs a stranger in cold; and the nightly reset has put it back the next
  morning.

## Later (post-launch — deliberately unplanned)

Phase 8's instruction stands: plan these against a deployed thing. Kept here so they are not
re-derived from scratch.

- Rate-limit storage is in-memory and per-process — honest for one gunicorn worker, wrong for
  two. `RATELIMIT_STORAGE_URI` is where a redis URL goes on the day the web tier scales.
- `remoteok` and `remotive` cannot be geo-narrowed at all, which is where the EU-remote reach
  still leaks; more boards is the only lever, and the two obvious ones were refused on their
  own robots.txt.
- `IDEA.md` is still empty, and only Oliver can fill it.


---

## CV framing

Bullets to grow into, each mapping to a phase above:

- Built and deployed a multi-tenant job-aggregation SaaS (Flask, Postgres, Docker Compose,
  Caddy) that scrapes 7 job boards and scores every posting against a user's CV.
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
- ~~**Phase 6:** start a scan and keep triaging jobs while it runs; open all four pages at
  375 px wide; get through Jobs and Settings on the keyboard alone; look at both colour
  schemes.~~ **Done 2026-08-20**, in a browser against a `.backup()` copy of the live
  2375-job DB (the app served from a scratch `DATA_DIR`, so the real database was never
  opened):
  1. A `running` scan row put the strip under the nav — phase, counts, cancel, dismiss — and
     the Jobs page stayed fully usable underneath it. Dismissing hid *that* scan
     (`sessionStorage` = its id) and it stayed hidden across the polls that followed.
  2. `j j j` walked the cursor down the list and `d` declined the third job: the count went
     781 → 780, the row left Matches, and the next job slid into the cursor — the triage loop
     the layout was always asking for.
  3. Both colour schemes, on every page. The score breakdown reads correctly in both: one
     filled bar at 100% for Skills, three hatched "not known" tracks for the components this
     job never parsed — which is the scoring invariant, finally visible.
  4. All five pages at 390 px: the tracker is labelled cards, the jobs are cards, the nav fits
     on one line. Two things were wrong and were fixed here — the tracker's ↗ dropped to a row
     of its own (grid → flex) and the nav wrapped "Sign out" onto two lines.
  5. `/api/stats` is requested once per dashboard load, "Load more" appended rows 51–100 of
     780 without a repeat, and the Settings error path (all four weights at zero) put the
     server's sentence beside its own button and re-enabled it.

  **Not covered:** a real scan was not run — the strip was exercised against a scan row rather
  than by scraping live boards, which is what the politeness delays are for.
- ~~**Phase 7:** open the public URL on a phone; the demo account must work from a cold
  start.~~ **Done 2026-08-24** — the *public URL* half is not possible (there is no box), so
  the rest was run against a local instance in a real Chromium at 390 px, and the cold start
  was run twice:
  1. **Cold start (a), an empty database.** No users, no jobs, `DEMO_MODE=true`. `/` served the
     landing page, one click on the demo button created the account and signed in, and all four
     app pages returned 200 with a coherent all-zeroes `/api/stats` — an empty demo rather than
     a stack trace. The demo did **not** take the admin slot: the signup that followed did.
  2. **Cold start (b), a populated pool with no accounts at all** — the box after its first
     scan and before anybody has signed up, from a `.backup()` copy of the live DB with every
     user row deleted. One click on a phone seeded the account against 2375 jobs and landed on
     the dashboard.
  3. **On a phone (390 px), through the real CSRF path.** All five pages. `j` then `d` moved
     the count 1806 → 1805, so triage works on a touch viewport too. This is where the nav
     overflow above was caught: `document.documentElement.scrollWidth` was 554 on all four
     pages before the fix and is 390 after it, with and without touch emulation.
  4. **The three holes, over the wire with a real token:** deleting the demo account is a 403
     with the demo's own message, uploading a CV to it is a 403, and starting a scan is a 403
     (with `SCAN_ENABLED=true`, so it is the admin check answering and not the kill switch).
  5. `/healthz` answered `{"status": "ok", "release": "dev", "checks": {"database": "ok"}}`,
     and a broken connection makes it a 503 with the traceback in the log and nothing but the
     word "error" in the body.

  **Not covered:** TLS, a real domain, and therefore the phone-on-the-actual-internet part of
  this checkpoint. Same blocker as Phase 5.
- ~~**Phase 8, the digest:** send one against real data, and prove a job is never sent
  twice.~~ **Done 2026-08-24**, against a `.backup()` copy of the live 2375-job database and
  a real SMTP conversation — a socket server started in the checkpoint process, so
  `mail._transport()`, the multipart build and the headers were all exercised rather than
  stubbed. The unit tests deliberately replace `mail.send`, which is the only honest way to
  assert on wording; this is the half that needed a socket.
  1. `init_schema` added `user_jobs.digested_at` to the live schema with 2375 jobs, the score
     sum of 108617.8 and the statuses (1 applied / 55 declined / 4694 new) all untouched.
  2. Both real accounts were due immediately — 783 and 1761 matches waiting — and each got
     one message: the subject ("783 new job matches (top 100%)"), `From:`, the text part
     ordered before the HTML one, `List-Unsubscribe`, and links on `PUBLIC_BASE_URL`. Capped
     at `DIGEST_MAX_JOBS`, and the message says how many more are waiting.
  3. A second pass inside the interval sent nothing, and the jobs queued for the *next*
     digest had no overlap with the ones already sent.
  4. Backdated a day, a second mail went out and no job was repeated across the two.
  5. **A refused mail server was then pointed at**: `send_due` did not raise, marked nothing,
     and did not retry on the next poll — and the same matches all arrived in the following
     digest once the server was back. That is the "latency, not matches" rule, run.
  6. The demo account was never a candidate, and a user who turned the setting off got
     nothing.
  7. `data/jobmatch.db` was byte-identical afterwards and the scratch copy was removed.

  **Not covered:** a real relay. Every message went to a socket on 127.0.0.1, so deliverability
  — SPF, DKIM, whether it lands in a spam folder — is untested and needs the box, like TLS.
  `DEPLOY.md §7` is where that is written down.
- **Phase 8, the first two items:** checked by tests rather than by a session at a
  browser — `tests/test_sources.py` and `SourceYieldTests` for the silent-board alarm,
  `tests/test_e2e.py` for the loop — which is the right shape for both: the failure the alarm
  exists to catch is invisible from the outside, so looking at a page could never have
  confirmed it. **Not covered:** the alarm has never fired against a *real* board. `ctx.seen()`
  counts what the parser found in fixture HTML, so what is still unproven is that the counts
  are right about profesia's and kariéra's live markup — which one scheduled scan on the box
  will settle, and until there is a box the honest answer is that it has not been.

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


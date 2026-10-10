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
**Phase 10 is not a substitute for it** — it is what is worth doing while the box is pending,
planned 2026-09-25 once Phase 9 had no agent-doable half left; Phase 9 resumes ahead of it the
day the box exists.

**Direction changed again on 2026-10-03, and this one outranks the paragraph above.** The
owner is job-hunting *now*, so the project's definition of done is no longer "deployed
multi-user SaaS" but the sentence in `MISSION.md`: *the end result is me getting a job that I
am happy with.* Read `MISSION.md` first — it is the brief in his own words, with the decisions
taken under it. In practice that means: Slovakia and Profesia only, Košice or remote, nothing
above junior, no email and no box this week, and a Jobs page stripped to a list that links out
to the board. Phases 9 and 10 are not cancelled; they are simply behind the only question that
matters, and the multi-user machinery stays working rather than being torn out — nothing new
gets built for a hypothetical user while this is true.

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
- A Jobs list that can be asked how old a posting is, and a scan that finishes so there is
  something fresh in it (2026-09-28, asked for directly rather than planned). 538 tests.
- The local instance made fit to actually live on (2026-10-01, asked for directly rather than
  planned): the shared crawl had been running since August on `local@jobmatch.local` — a
  passwordless pre-Phase-3 row that `db.admin_user_id` preferred for being id 1 — so the owner's
  boards and terms were read by no scan and could not be corrected from the UI; and the `.env`
  feeding both processes was being read by neither, python-dotenv having been absent from the
  interpreter while `config.py` swallowed the ImportError. Both are now migrations and refusals
  rather than facts somebody has to notice. 556 tests.

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
  `db`+`web`+`worker` were brought up and verified (below). ~~**`caddy` is the one service
  still unexercised** — it needs a real domain to complete an ACME challenge, so it cannot be
  tested locally and is verified on the box or not at all.~~ Wrong, and expensively so: only
  the ACME challenge itself needs a real domain, and everything else in `deploy/Caddyfile`
  was exercised on a laptop by Phase 9 item 2 — which is how the body cap was caught doing
  nothing at all. What is still box-only is the challenge, and that is item 5.
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

## Phase 9 — 🚢 Cross the ship line (planned 2026-08-29; items 1–3 done, 4–10 open; item 4 re-planned onto a free ARM box 2026-09-12, its box-free half — CI on `linux/arm64` — landed the same day, and on 2026-09-13 the arm64 build and a running aarch64 Chromium were proven locally, which also found that CI's Chromium check could never fail; item 6's box-free half — "can this deploy check fail?", answered no — landed 2026-09-17, as did item 5's, which found a first boot crawling the boards on the demo account's settings before the admin existed; item 7 was re-planned onto a free target the same day — an object store, because Oracle reclaims idle *compute*, which is what a backup VM is — landing its box-free half; item 8's box-free half — are the `seen` counts right about the boards' *live* markup? — landed 2026-09-22, finding all seven exact and Kariéra's alarm unable to fire; item 9's box-free half — a real SMTP conversation, which nothing in the suite had ever had — landed 2026-09-23, finding every message leaving without a `Date` or a `Message-ID`, 8-bit bodies under an envelope that never declared them, and credentials handed to an unencrypted socket; item 8's own parked follow-up — the Remotive stub, which it said wanted confirming a second time before code was written around it — was confirmed and fixed 2026-09-23, taking that board from 19 requests a scan to 1. **Items 4–10 are otherwise blocked on Oliver provisioning the box and the subdomain — no agent can do that half, and as of 2026-09-25 every half that did not need one has landed: there is no agent-doable box left in this phase. `## Phase 10` was planned that day for what is still worth doing while the box is pending, and it waits the moment the box exists.**)

Phase 8 asked that the next phase be planned **after** deployment, "against a deployed thing
rather than an imagined one". This phase does not break that rule: it is *the deployment*, not
the features that come after it. Nothing here invents a capability — every item is either the
work Phase 5 left behind, or a check that some earlier phase recorded as "not covered, needs
the box". Post-launch ideas stay in `## Later` below, unplanned on purpose.

Two things found while planning it, both of which change what this phase has to contain:

- **The last two phases were not in the repository** (fixed by item 1 on 2026-09-02).
  `main`, `origin/saas` and the working branch `phase6-ui` all pointed at the same commit
  (`6b62e1f`), and 62 files were uncommitted —
  which was Phase 7 and Phase 8 in their entirety: `landing.html`, `job.html`, `digest.py`,
  `mail.py`, `obs.py`, `places.py`, `demo.py`, `sources/jobscz.py`, the FX salary work and ten
  test files. `deploy.yml` deploys the commit CI went green on, on `main`. So the pipeline as
  it stood would have put a JobMatch on the box with no landing page, no demo, no digest, no
  places, no Czech board and no currency conversion — and until then a laptop's working tree
  was the only copy of a third of this project.
- **It is six repository secrets, not four.** Phase 5 and Phase 8 both say "the four
  repository secrets in `DEPLOY.md §6`"; §6 lists six and `deploy.yml` reads all six —
  `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PATH`, `DEPLOY_SSH_KEY`, `DEPLOY_HOST_KEY`,
  `DEPLOY_DOMAIN`. Four of them armed is a workflow that fails at the step after the one you
  were watching.

Items 1 and 3 need no box and should go first; 2 needs no box either and is worth doing
*before* one exists, because Let's Encrypt rate-limits failure. Everything from 4 down is
gated on an account and a domain.

**Item 4 was re-planned on 2026-09-12 onto a free path, because the thing gating this phase
was a purchase and Oliver asked for a free option outright.** It had stalled four sessions
running on "[Oliver] Buy the box and the domain". A no-cost box is an ARM box, and that is
not a free swap — it changes the CPU architecture every container runs on, so the re-plan
comes with the architecture question answered rather than deferred to the box. See item 4.

- [x] **1. Get Phase 7 and Phase 8 into `main`.** Review the 62 changed files, commit them on
  a branch, and merge — the ordinary flow, but it is the first item in this phase because
  every later one deploys whatever `main` holds, and because a green suite in an uncommitted
  tree protects nothing. Check `.gitignore` still excludes the database, `data/` and `.env`,
  and check no CV or scraped row rides along. `origin/saas` and `phase6-ui` both sitting on
  the old commit is worth resolving at the same time rather than leaving three names for one
  thing. **Verify:** `git status` clean, `origin/main` at the new commit, the `test`,
  `postgres` and `image` jobs of `ci.yml` all green on it — the image job in particular, since
  nothing has built the Dockerfile since `jobscz` added a Playwright path to a *detail* fetch.
  → Landed as `019359d` on `main` (71 files, +10 124/−602): Phase 7's landing page,
  job page, favicon and the ten screenshots with `tools/screenshots.py`, and Phase 8's
  `demo`, `digest`, `mail`, `obs`, `places`, `jobscz` and the FX salary work. All four
  CI jobs green on it — `test (3.11)`, `test (3.12)`, `postgres` and, the one that had
  never run since `jobscz`, `image`. Nothing personal rode along: `.env`, `data/jobmatch.db`
  and `data/resumes/2.pdf` (a real uploaded CV) are all still ignored, and the screenshots
  were checked by eye rather than assumed — they are shot through the seeded demo account,
  so what they show is the same demo data a stranger sees. The three names are now one:
  `phase6-ui` deleted, `origin/saas` deleted, and `saas` dropped from `ci.yml`'s push
  triggers so the config stops naming a branch that no longer exists.
- [x] **2. Exercise `caddy` without a domain.** Phase 5 recorded that `caddy` "cannot be tested
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
  → All five verified on a real four-container stack against the **shipped** Caddyfile,
  driven over `curl --resolve jobmatch.test` so no `/etc/hosts` entry was needed: TLS 1.3 +
  HTTP/2 with the chain actually **verified** against Caddy's local root (`--cacert`, not
  `-k`); the four headers exact on the landing page and `Server` absent; a 308 to
  `https://` preserving path and query. The file itself gained one line —
  `{$CADDY_GLOBAL_OPTIONS}` in the global block, empty in production — so `local_certs` here
  and item 5's staging `acme_ca` both come from the environment and **the box never needs
  this file edited**. Also silenced the "input is not formatted" warning Caddy logged on
  every boot.
  **The body cap was dead config, and that is the finding.** A 25 MB POST *was* 413'd — by
  **Flask**, not by the proxy: the response carried `Vary: Cookie` and `web` logged the
  request, so it crossed the proxy exactly as the Caddyfile's own comment said it could not.
  `request_body max_size` only errors when the upstream **reads** past the limit, and Flask
  never does — over `MAX_CONTENT_LENGTH` it refuses on the Content-Length alone without
  touching the body. A Content-Length matcher now rejects at the edge: **413 with
  `uploaded=0` and zero requests reaching `web`**, exact at the boundary (20971520 passes,
  +1 rejects). It has to be **one CEL expression**, not a `header` matcher sitting next to an
  `expression` one — matchers in a set are evaluated independently, so the header guard does
  **not** stop the `int()`, and `int("")` on every request without a Content-Length, i.e.
  every GET, is **a 500 for the whole site**. That was measured before it shipped, not
  reasoned about. `max_size` is kept and does earn its place: a chunked 25 MB form, which the
  matcher cannot see, was 413'd by Caddy with `web` never logging it.
  **The proxy-header check was made to fail first.** 30 CSRF-valid POSTs from the host =
  20 × 200 then 10 × 429 (the limit is 10/min but gunicorn runs two workers over an
  in-memory store, so 20 is correct), while a container on another IP got 200 200 200. With
  `TRUSTED_PROXY_HOPS=0` the same run logs `172.28.0.5` — the `caddy` container — as the
  client for **every** request, and the second client is locked out 429 429 429 by traffic it
  never sent. So the check can fail, which is what makes it worth passing.
  Cost two false starts worth writing down: CSRF must be satisfied first or the limiter never
  counts (a token-less POST is a 303 from the CSRF handler and 30 of them produced not one
  429), and the `-Server` header does **not** cover the 308 — the automatic redirect is a
  separate server that never sees the site block — while `Via: 1.1 Caddy` names the proxy on
  every response anyway, so stripping `Server` is cosmetic. Left as-is: writing an explicit
  `http://` block to fix it would replace Caddy's automatic redirect and put the ACME
  HTTP-01 challenge in the way of a hand-rolled one, which is a bad trade on the item
  before the first certificate. Suite unchanged at 433 passed / 12 skipped, `ruff check`
  clean.
- [x] **3. Correct `PROJECT.md`, which today's work made wrong.** It says six source adapters
  (seven), 318 tests (433), and carries **"No FX conversion for salary"** as a key decision —
  reversed outright this morning. A stale count is untidy; a reversed decision left standing
  as a decision is the kind of staleness that misleads, and `PROJECT.md` is the file that
  exists to say *why*. Its "Known rough edges" also still describes a Phase 5 that this phase
  is about to close. **Verify:** every claim in "Current state" re-read against the tree, not
  against the roadmap.
  → Re-read against the tree, and it was wrong in more places than the item named. Counted
  from the code: **seven** adapters (the registry, not the folder — `base.py` is not one),
  **433 passed / 12 skipped** from an actual run, and **6842** jobs in `data/jobmatch.db`,
  not 2375. **"No FX conversion for salary" is now the opposite decision**, written out with
  the reason it was reversed rather than deleted, because a decision that changed is worth
  more than one that was quietly dropped. Two the item had not spotted: the remote bullet
  still said remote is matched on **`jobs.country`**, a single column that the "five places"
  work replaced with the packed `jobs.countries` — the exact bug that stored "LATAM, Europe,
  USA, Canada, APAC" as `US` — so it now has a bullet of its own; and **"Built" claimed
  Phase 7 plus three of Phase 8**, when Phase 8 closed on 2026-08-29 and two Phase 9 items
  have landed since. The rough edges were re-scored, not just re-worded: `caddy` and TLS come
  **out** of "never run" (item 2 verified them locally against the shipped file; the real ACME
  challenge, `deploy.yml` and the public URL stay), `IDEA.md` is no longer empty but is one
  line under its placeholder, and the rate-limit note stops being hypothetical — the image
  ships `--workers 2`, so the per-process store is a **live** defect, measured at 20 requests
  through a 10/min limit. Docs only; suite re-run unchanged at 433/12.
- [ ] **4. A box and a domain, both free — which means an ARM box.** Re-planned 2026-09-12;
  the original text was "[Oliver] Buy the box and the domain: Hetzner CX22", ~€4/mo, and it
  stalled this phase for four sessions. The free equivalents are an **Oracle Cloud Always Free
  Ampere A1** instance in an EU region (Frankfurt or Amsterdam, so CVs stay in the EU as
  `DEPLOY.md` intends) and a **free subdomain**, and each brings a constraint the paid version
  did not:

  - **Always Free A1 is 2 OCPU / 12 GB, not the 4 / 24 everyone quotes** — Oracle halved it on
    2026-06-15 and their own docs now read "1,500 OCPU hours per month … equates to 2 OCPUs
    and 12 GB of memory", plus 200 GB of block storage. That is still *more* box than the
    CX22 this was sized for (2 vCPU / 4 GB), so the sizing is not the problem.
  - **The reclamation rule is, and it is the one thing to plan around.** Oracle reclaims an
    Always Free instance when, over a rolling 7-day window, 95th-percentile CPU **and**
    network **and** memory are all under 20 %. JobMatch idles below every one of those:
    Postgres, two gunicorn workers, the scan worker and Caddy sitting still come nowhere near
    2.4 GB of a 12 GB box, and at `SCAN_INTERVAL_HOURS = 6` a crawl of even ten minutes is a
    ~3 % duty cycle, so p95 CPU stays flat. The standard exemption is upgrading the tenancy to Pay As You Go —
    Oracle's docs say plainly that "Oracle doesn't charge for Always Free resources after you
    upgrade" — but it puts a card on file, which is exactly what this re-plan is avoiding.
    **Decide this before provisioning, not after the box disappears**; the alternative is to
    size the instance so idle memory clears 20 % rather than to manufacture busywork.
  - **A free domain is a subdomain**, and the two that need no eligibility are `duckdns.org`
    and `eu.org`. Both are **on the Public Suffix List** (verified against the list itself —
    lines 13015 and 13398), which is the part that actually matters: Let's Encrypt counts its
    certificates-per-registered-domain limit per *your* subdomain rather than pooling every
    DuckDNS user into one bucket, so a real certificate is reachable. `eu.org` is permanent
    but wants your own nameservers and is approved by hand over weeks; `duckdns.org` is
    instant and is the one to start on. GitHub Student Pack's Namecheap `.me` is free for one
    year only and needs current enrolment, so it is a nice-to-have, not the plan.
  - **`deploy.yml` builds the image on the box**, so the box builds for its own architecture
    and no registry or cross-push is involved — but CI's `image` job builds amd64 only, which
    means **nothing has ever built this Dockerfile on arm64** and the box would be the first
    place it is tried. Teach the `image` job `platforms: linux/amd64,linux/arm64` *before*
    provisioning: it is the one arm64 check that needs no box, and item 5 is a bad place to
    discover a build failure.
    → **Done 2026-09-12 — but not as this bullet wrote it, because that literal would have
    cost the smoke test.** `load: true` is single-platform only ("only compatible with
    single-platform builds", per the action's own IO reference), so `platforms:
    linux/amd64,linux/arm64` on the one job emits a manifest list the runner's docker image
    store cannot take: the build would go green and the `docker run` step that proves the
    image *runs* — rather than merely builds — would stop working. `image` is now a **matrix
    over `platform`**: one job per architecture, each keeping `load` and the run check,
    `setup-qemu-action` on the arm64 leg only, and the `type=gha` cache `scope`d per platform
    so the two legs stop overwriting each other with layers the other cannot use. A red job
    now also names the architecture that broke. It gained one check the amd64-only job never
    needed — Chromium's **`e_machine` read out of the ELF header inside the built image** and
    asserted against the leg's platform (0x3e / 0xb7), because the base image ships browsers
    per architecture and "builds clean but carries the other arch's browser" is exactly how
    this fails quietly. That step was **made to fail before it was trusted**: driven against
    synthetic ELF headers both ways it exits 0 on a match and non-zero on a mismatch, so it
    is not a step that can only pass. **Still unverified: the arm64 build itself.** Docker
    Desktop on this machine reports "already running" over a dead socket and has not started
    its VM since 2026-09-07, so nothing here can build it, and CI cannot until the branch is
    pushed — which is why this item's box stays unchecked and the rest of it is still
    Oliver's to provision.

  **The architecture risk was verified rather than deferred** (2026-09-12), because "free box"
  silently means "ARM" and the image drives a real Chromium. All of it checked against the
  registry and PyPI, since Docker Desktop would not start on this machine:
  `mcr.microsoft.com/playwright/python:v1.62.0-noble` publishes a **linux/arm64** manifest;
  that image's own build history runs `playwright install --with-deps` under
  `uname -m = aarch64`; its browser layer contains
  `ms-playwright/chromium-1234/` — **the exact revision Playwright 1.62.0 pins**, carrying
  `INSTALLATION_COMPLETE` — and the `chrome` binary inside it, read out of the layer and
  inspected byte-wise, is **ELF64 with `e_machine` 0xb7, AArch64**. Playwright also publishes
  `chromium-linux-arm64.zip` for revision 1234 (204 MB) for the non-Docker path. Every
  compiled dependency has a cp312 aarch64 manylinux wheel — `psycopg2-binary`, `lxml`,
  `greenlet`, `cffi`, `SQLAlchemy`, and `argon2-cffi-bindings` through a `cp310-abi3` wheel,
  which is the one that looks missing if you grep for `cp312` and stop there.
  **What is still unproven:** that *our* Dockerfile builds on arm64 (nothing has ever tried),
  and that Chromium launches inside the worker's 1500m limit on 2 OCPU — the second is item
  8's job and always was.

  → **Both of those are now proven, and the first sentence above was wrong when it was
  written** (2026-09-13). "Nothing has ever tried" was checkable and was not checked:
  `jobmatch:latest` has been sitting in this laptop's image store since **2026-09-05**,
  `linux/arm64`, built during item 2's four-container stack run — seven days *before* the
  claim — and `Dockerfile` and `requirements.txt` are both untouched since `6b62e1f`
  (2026-08-19), so it was built from the byte-identical files that ship today. The
  architecture question was answered by a build a week earlier and nobody looked.

  Rather than rest on a six-day-old image, it was rebuilt from scratch: **`docker build
  --no-cache --platform linux/arm64` on this machine, which is native `aarch64` and not
  QEMU.** Exit 0, **zero `CACHED` layers** — the first attempt hit that same 09-05 cache and
  reported success in nine seconds having compiled nothing, which is why the run that counts
  is the `--no-cache` one. Every compiled dependency resolved a **prebuilt aarch64 manylinux
  wheel with no sdist and no `Building wheel for` line anywhere in the log**, and the real
  build covered five the 09-12 registry check never enumerated: `cryptography`
  (`cp311-abi3`), `pillow`, `pypdfium2`, `wrapt` and `charset_normalizer`, alongside the
  `psycopg2-binary` / `lxml` / `greenlet` / `cffi` / `SQLAlchemy` / `argon2-cffi-bindings`
  that were predicted.

  **Chromium was launched, not merely inspected.** CI reads an ELF header; that proves the
  file is AArch64, not that it runs. Inside the image, under the worker's *own* compose
  limits (`--memory=1500m --shm-size=512m`) and with `scan.py`'s exact
  `args=["--disable-gpu", "--no-sandbox"]`, Chromium **151.0.7922.34 started, opened a page
  and rendered text**, with `platform.machine()` reporting `aarch64`. That is not a
  substitute for item 8 — this is an M-series laptop, not 2 OCPU of Ampere, and the crawl's
  real memory curve is still unmeasured — but "the browser will not even start on ARM" is
  now off the table.

  **And the CI step that was supposed to catch all this could never have failed.** The
  Chromium check landed on 09-12 runs `docker run --rm --platform … jobmatch:ci python3 -
  <<'PY'` — **without `-i`**. Without `-i` the container gets `/dev/null` for stdin,
  `python3 -` reads an empty program, and the step exits 0 having executed nothing. Measured
  head-on: a script whose only statement was `sys.exit("THIS SHOULD FAIL")` **exited 0 and
  printed nothing**; adding `-i` made the identical script print and exit 1. The 09-12 note
  says that step "was made to fail before it was trusted" — the *script's logic* was, driven
  against synthetic ELF headers, but the *step* never was, and the bug was in the wiring
  around it rather than in the code being tested. `ci.yml` now passes `-i`, with a comment
  saying why so it is not tidied away. So the arm64 leg of `image` has, until now, been
  asserting nothing about Chromium at all.

  **Verify:** `ssh deploy@host docker compose version` answers over key-only SSH with password
  auth refused; `uname -m` on the box says `aarch64`; the subdomain resolves to the box from
  off the network; ports 80 and 443 are reachable from outside, which on Oracle means **both**
  the VCN security list and the instance's own iptables — Oracle's Ubuntu images ship a
  default-REJECT ruleset, and a security-list rule alone leaves the port silently dead; and
  CI's `image` job is green on `linux/arm64` before any of this is trusted.
- [ ] **5. First boot, and the first certificate.** `.env` from `.env.example` — `SECRET_KEY`
  from `secrets.token_hex(32)` and not the dev key, `POSTGRES_PASSWORD`, `DOMAIN`,
  `ACME_EMAIL`, `PUBLIC_BASE_URL` — then `docker compose up -d --build --wait`, then
  `setpassword` for the first admin. Point `acme_ca` at staging for the first issuance and
  only then take it off, so a Caddyfile mistake costs a staging cert and not a week of the
  real rate limit. On item 4's ARM box the `--build` here is the **first real arm64 build**
  of this Dockerfile and it will not be fast: the base image's browser layer is 832 MB
  compressed and there is no warm cache on a fresh instance, so budget for it rather than
  reading a slow first boot as a hang. **Verify:** `https://$DOMAIN/healthz` returns `{"status": "ok"}` over a
  publicly-trusted certificate; all six pages load; the session cookie carries `Secure`
  (which is `mark_deployed()` doing its job through gunicorn, the one path `wsgi.py` exists
  for); and `SSLLabs`/`curl -I` shows HSTS on the real host.

  → **The box-free half landed 2026-09-17, and running it found that the first boot starts
  crawling the job boards before the admin exists.** The whole of this item except the public
  name was driven on a real four-container stack, from a `.env` copied out of `.env.example`
  with exactly DEPLOY.md §2's table filled in (the one laptop deviation being
  `CADDY_GLOBAL_OPTIONS=local_certs`, since the name has no public DNS):

  - **`up -d --build --wait` brought all four containers up healthy in 14 s**, `/healthz`
    answered `{"status": "ok"}` over a certificate that verifies against its issuing CA and
    fails without it (curl exit 60), HSTS was on the response, and the landing page, `/login`,
    the dashboard, `/jobs`, `/tracker` and `/settings` all loaded — five as a logged-in admin
    created by `setpassword` inside the container. `/jobs/<id>` is the one page this could not
    load: a fresh box's pool is empty until the first scan, which is item 8.
  - **The scheduler queued a crawl ten seconds after `up`, and it was not the admin's.** At
    +0.2 s the worker created the demo account; at +10 s it queued `scan 1 (schedule, requested
    by 1)`; at +21 s it was crawling the live boards for real, on the demo persona's search
    terms, and the admin did not yet exist. `due_for_scan` *has* a guard for this — "a fresh
    instance with no account has no search settings either" — but it asked
    `db.admin_user_id(conn) is None`, and that one falls back to the first account: on a
    demo-enabled box the first account is the demo, created by the very worker the guard is
    guarding. `db.has_admin` exists for exactly this distinction (its docstring says the demo
    "may well be user 1 on a fresh box"), so the schedule now asks that instead. The two tests
    that should have caught it sit in different files and each saw half: one deletes the only
    account, the other checks the demo's `is_admin` flag and says in its own name that this is
    what stops it triggering the shared crawl — true of the button, false of the schedule.
    Re-measured after the fix: **45 s of an untouched fresh boot, 0 scans**, and the scan
    queued within 10 s of `setpassword`, `requested by 2` — the admin.
  - **`mark_deployed()` was made to fail before it was trusted.** With `HOST` at the
    `127.0.0.1` the example ships — which is right, since gunicorn binds with `--bind` — the
    container reported `config.SESSION_COOKIE_SECURE = False` while the cookie came back
    `Secure; HttpOnly; SameSite=Lax`. Commenting the one call out of `wsgi.py` and restarting
    dropped `Secure` from the header, and restoring it brought it back. That is the verify
    clause above proven in the configuration where it is load-bearing rather than incidental,
    and nothing in the suite had ever called either function.
  - **Both startup refusals turn a first boot red rather than quiet.** A blank `SECRET_KEY`
    and the `JOBMATCH_DEBUG=1` `.env.example` ships each made gunicorn's worker fail to boot,
    the container restart-loop, and `docker compose up --wait` exit **1** with `web is
    unhealthy` — which is item 6's healthcheck earning its place four days early. Both fired
    with `HOST` still on loopback, because `wsgi.py` passes `deployed=True` rather than asking.
  - **`tests/test_firstboot.py`** (15 tests) keeps all of it: the refusals, `mark_deployed`'s
    four behaviours, that `wsgi.py` still calls both and still does not start a scan thread,
    and that every environment variable any module reads is offered by `.env.example` — which
    found `LOCAL_USER_EMAIL` missing from it. Every one was made to fail first, by mutating
    the file it guards.

  **Still Oliver's:** the box, the domain, the real ACME issuance, and a certificate a browser
  trusts without being told to.
- [ ] **6. Arm the pipeline — all six secrets.** `DEPLOY.md §6`, corrected to six.
  **Verify:** an empty commit on `main` goes green in CI, triggers `deploy.yml`, and the
  workflow's own `https://$DOMAIN/login` smoke test passes — and then a deliberately broken
  container makes the workflow *fail* rather than quietly serve a 502, because a deploy check
  that cannot fail is not a check (the same standard `restore-check.sh` was held to).

  → **The box-free half landed 2026-09-17, and it is the second half of that verify clause
  — the one that does not need the box, because "can this check fail?" is answerable here.**
  It could not. Both halves of the deploy's checking were driven rather than read, and each
  was broken on purpose first:

  - **`docker compose up --wait` cannot fail for a service that has no healthcheck.** Measured
    on compose v2.39.2: a container that had exited 1 and restart-looped six times was printed
    as `Healthy` and `--wait` exited **0**, in six seconds. `db` and `web` declared a
    healthcheck; **`worker` and `caddy` did not** — so the A/B against the shipped file, with
    the worker's command replaced by one that dies at boot, is exactly that: **before, `up
    --wait` said `Container jobmatch-worker-1  Healthy` and exited 0** while the container sat
    at `state=restarting exit=1 restarts=8`; after, `container jobmatch-worker-1 is unhealthy`,
    exit 1. A deliberately broken *worker* deployed green, and nothing downstream noticed it —
    the smoke test only ever reaches `web` through `caddy` — so the first thing that would have
    told anyone is item 8 finding no scan had run, plus no digests and no demo reset. Both
    services now declare one; the worker's asserts what a second process in that container can
    actually see (the app imports, the database answers), which covers boot failures and a
    vanished Postgres but **not a loop that is alive and wedged**, and says so.
  - **The smoke test asserted only an HTTP status code**, so it could not tell "this commit is
    live" from "something answers on this name": a parked nginx page at the same hostname
    returned 200 and **the deploy went green**. That is not hypothetical on item 4's plan,
    where the box is reclaimable and the subdomain's A record is set by hand. The fix was
    already half-written and never wired: `config.py` and `.env.example` both say "the deploy
    workflow passes the sha", and **`deploy.yml` never set `RELEASE` at all** — so `/healthz`
    on the box would have reported `"release": "dev"` forever and every Sentry event would have
    been tagged `dev`. The deploy now passes `RELEASE="$SHA"`, compose hands it to `web` and
    `worker`, and the smoke test reads it back and compares. Confirmed end-to-end on the real
    four-container stack: `/healthz` through Caddy answered the exact sha that was passed in.
  - **Driven, not read.** The two shell bodies were pulled out of the shipped `deploy.yml` and
    run the way Actions runs one (`bash -e`, the step's `env:` in the environment) against a
    **real sshd** with stubbed `docker`/`git`, and a **real TLS endpoint**. The good path
    exits 0 and the remote genuinely executes all five commands — which is the check ci.yml's
    missing `-i` failed four days ago. Every failure now exits non-zero: compose unhealthy (1),
    an absent commit (128), an unreachable box (255), a 502 (22), `/healthz` 503 (22), an
    untrusted certificate (60), a parked page (1), and **a box still serving the previous
    commit (1), which nothing could catch before**.
  - **`tests/test_deploy.py`** (7 tests) keeps all of it from being tidied away: every service
    declares a healthcheck and none disables it, the deploy still passes `--wait` and
    `RELEASE="$SHA"`, the smoke test still reads `/healthz` back, and every secret the workflow
    reads is named in `DEPLOY.md`. Each was **made to fail before it was trusted**, and that
    caught one dead guard among them: `assertIn("--wait", …)` matched the word in the *comment*
    above the command and passed with the flag deleted.

  **Still Oliver's, and still the whole point of the item:** the six secrets, and a real run.
- [ ] **7. A backup that survives the box — re-planned 2026-09-13 onto a free target.**
  Item 4 went free on 2026-09-12 and left this one still saying "order a Hetzner Storage Box";
  this is the same treatment. What matters is that the dump leaves the box, not who stores it.
  Put `backup.sh` on a nightly cron with `REMOTE_TARGET` set — it warns while it is unset, and
  it is right to: a backup that only exists on the box is not a backup if the box is what dies.

  **The free path is an object store, and that is forced rather than chosen.** The obvious
  free swap is a second Always Free VM, which would need no code change at all, since
  `REMOTE_TARGET` was already an rsync/ssh target. It is the one option that cannot work.
  Oracle's reclamation rule — the one item 4 plans around — applies to **compute instances
  only**: their own doc says "Idle Always Free **compute instances** may be reclaimed", on
  95th-percentile CPU < 20 % **and** network < 20 % **and** memory < 20 % (A1 only) over 7
  days, and lists no such rule for Object Storage or block volumes. A machine whose entire job
  is to receive one 5 MB file at 03:17 is idle by definition, so a backup VM is the resource
  Oracle is likeliest to delete *for working correctly* — and it would take the backups with
  it. Buckets are not subject to that rule.

  **The target: an Oracle Object Storage bucket in the same EU home region as the box.**
  Always Free gives **20 GB** combined Standard/Infrequent Access/Archive, **50 000 API
  requests per month** and 10 TB/month of outbound transfer — against two objects a night and
  a restore now and then, none of those is a limit this can reach. It also needs no new
  account, no card, and no second machine to patch. One knock-on for item 4, verified on the
  same page: **both Always Free compute shapes must be created in the tenancy's home region**,
  and the home region is fixed at signup — so item 4's "Frankfurt or Amsterdam, so CVs stay in
  the EU" is this item's decision too, made once, at signup, irreversibly.

  **The honest weakness is that this is the box's own tenancy.** It survives every likely
  death — the instance reclaimed, the boot volume lost, the box compromised — but not the
  tenancy being closed. That is cheap to fix later precisely because the transport is now
  `rclone`: a second vendor is a config line and a second cron entry, and Backblaze B2's
  10 GB free tier (its own rclone backend) is the drop-in. Oracle also exposes an
  S3-compatible endpoint with Customer Secret Keys, so nothing here is locked to one vendor.

  **Sizing was measured, not estimated:** a gzipped dump of the live 7 970-job / 20 730-score
  pool is **5.4 MB**, and the CVs 52 KB. Fourteen nightly copies is ~78 MB against 20 GB.

  → **The box-free half landed 2026-09-13**, and writing it found two defects that a 1 TB
  paid Storage Box would have hidden for years:
  - **Nothing ever pruned the remote.** `backup.sh` deleted local copies older than
    `KEEP_DAYS` and pushed to the remote forever. On a finite free tier that is a slow leak
    with a certain end. There is now `REMOTE_KEEP_DAYS` (defaulting to `KEEP_DAYS`), pruning
    by `--include` patterns so unrelated objects in the bucket are untouched — checked: a
    30-day-old dump was deleted and a `NOTES.txt` of the same age was not.
  - **Nothing could ever pull.** This item's verify has always demanded a restore from a dump
    *pulled back from the remote*, and no code path fetched one — so the only thing that could
    ever be restored was the local copy, which proves `pg_dump` works and proves nothing about
    whether the off-box copy is real. `deploy/backup-pull.sh` now fetches it (`--latest` or a
    stamp), into its own directory rather than over the local copy, because a round trip you
    cannot tell from a local read is not a round trip.

  `REMOTE_TOOL` (`rsync` | `rclone`) now selects the transport; the rsync arm is byte-for-byte
  the old behaviour, for an ssh target that still makes sense. **Verified without a box**, by
  driving the whole of `backup.sh` with a stubbed `docker` against a local rclone backend:
  push, prune and pull all work, the pulled file is byte-identical to the dump, and restoring
  it reproduces `jobs=7970`, `user_jobs=20730`, `sum(match_score)=167034.7` — the same three
  numbers `restore-check.sh` compares. Each guard was **made to fail before it was trusted**:
  a corrupt remote copy fails the pull, an empty remote fails `--latest`, an unknown
  `REMOTE_TOOL` exits 2 before the dump rather than after it, and a colliding name is refused
  with the existing backup intact. Driving it rather than reading it is what caught the
  **first-ever run failing**: `rclone lsf` exits 3 with "directory not found" on a prefix that
  does not exist yet, so under `set -e` the collision check turned night one into a failure
  that copied nothing. A failed listing now means "nothing there to clash with" — and an
  unreachable remote still exits non-zero, because the copy underneath it is the operation
  that has to work.

  **`--immutable` was the guard until it was measured.** `rclone copy --immutable` documents
  "Source and destination exist but do not match: immutable file modified" for exactly this
  case. On rclone v1.75.1 it logged `Copied (replaced existing)` and **exited 0**, replacing a
  5.7 MB dump with a 391-byte file. It is now an explicit `lsf`-then-refuse check, because a
  guard that cannot fire is worse than no guard — it is the one you stop checking.

  **Verify (needs the box):** `backup.sh` on a nightly cron stops warning and the objects
  appear in the bucket; then `backup-pull.sh --latest` on the box fetches one back and
  `restore-check.sh` run **on that pulled file** exits 0 with all seven tables and
  `sum(match_score)` matched. The local-copy restore was already proven and the round trip is
  now proven against a local backend; what a real bucket still adds is the credentials, the
  network and Oracle's own API — which is the half no laptop can cover.
- [ ] **8. The first scheduled scan — which is the silent-board alarm's first real test.**
  Phase 8 built the alarm and said plainly what was still unproven: `ctx.seen()` counts what
  the parser found in *fixture* HTML, so whether the counts are right about profesia's and
  kariéra's live markup is unknown. One scheduled crawl on the box settles it, and it settles
  the Playwright-in-a-container question at the same time. **Verify:** a scan reaches `done`;
  every enabled board reports a non-zero seen count; if one reports zero, the alarm has worked
  and that adapter's selectors are the next task, not a bug in the alarm. Watch memory against
  the worker's 1500m limit while Chromium is up — and on item 4's ARM box this is also the
  first time an **aarch64** Chromium is launched by anything we own. The binary was confirmed
  to be there and to be AArch64; that it *runs* under 1500m on 2 OCPU is what this item
  measures. A Chromium that dies here is a `shm_size`/limit question, not a missing browser.

  → **The box-free half landed 2026-09-22, and it is the half this item's own text called
  unknown: whether the counts are right about the boards' live markup.** They are — all seven,
  exactly — and checking it found that on Kariéra the alarm could not have fired anyway.

  **Every enabled board was driven live from this laptop** (`search()` through a real
  `ScanContext`, two terms, a 7-day window, every response kept) and each `ctx.seen()` report
  was cross-checked against the response itself rather than against a fixture — the whole point,
  since a fixture is where the count came from:

  | board | seen | checked against | |
  |---|---|---|---|
  | Profesia.sk | 130 (20×6 + 10) | distinct `id="offerN"` per page — 20/20 on all seven pages | exact |
  | Kariéra.sk | 6, 8 | the board's own *“Aktuálna ponuka práce (6)”* / (8) | exact |
  | Jobs.cz | 749 | `article.SearchResultCard` — 749/749 across 26 pages; the board's own “Našli jsme 158 / 590 nabídek” | exact |
  | Remote OK | 99 | 100 array elements, 99 carrying an `id` | exact |
  | Remotive | 18 + 18 | the payload's own `job-count` | exact |
  | Jobicy | 50 + 50 | the `jobs` arrays | exact |
  | Arbeitnow | 800 | the `data` arrays, 250+250+100+100+100 | exact |

  Two off-by-ones are the live feed moving, not a miscount: Jobs.cz served 591 rows for a stated
  590 (590 distinct — one ad appeared twice across twenty pages as a new one shifted the window,
  over four minutes of politeness delays), and Arbeitnow 800 rows / 799 distinct the same way.
  `seen` counts rows served, which is the right thing for an alarm. Profesia's two 21-row pages
  are a `li.list-row native-agent` — the e-mail-alert signup — correctly not counted as an offer.

  **The finding is Kariéra's, and it is about whether the alarm can fire, not whether the number
  is right.** Its `seen` was `len(div.offer) - len(div.offer.highlight)`: the card *container*,
  computed outside `parse_offers` on a second `BeautifulSoup` pass. Profesia counts `listed`
  only after the title, the href and the id have been read (“a redesign that leaves the rows in
  place but moves the title or the link is still an offer we cannot read”), and Jobs.cz says the
  same in its own comment — Kariéra was the one board of the three that did not, and it is the
  one with no test for it. Measured by breaking the **live** page six ways and driving the real
  `_search_term` over it: renaming the title heading, changing its `h2` to an `h3`, reshaping the
  offer URL and dropping the id from it each left **`seen` at 6 while the parser read nothing** —
  four silent redesigns out of six. Only the container class changing, and the results list
  emptying, ever tripped it. `seen` now reports what was read, and all six fire.

  **Pagination had to keep asking the other number, and that is not a detail.** Kariéra stops on
  “fewer than `PER_PAGE` offers listed”, so had the read count simply replaced the card count,
  the first page carrying a promoted `redirect.php` slot — most of them — would have ended the
  crawl for that term. `parse_offers` now returns both (`listed` for the alarm, `rows` for the
  page-is-full test) and parses the page once instead of twice. Five tests in
  `KarieraSeenTests`, each **made to fail before it was trusted**: four mutations of the shipped
  file (the alarm told the card count again; pagination asking the read count; a card counted as
  read before its title link is found; an unreadable offer URL counted as read) are all caught,
  and the last two would each have passed the suite as it stood this morning. 483 tests, ruff
  clean. Re-probed live afterwards: **6 and 8, unchanged** — the fix alters nothing a healthy
  board reports, only what a broken one does.

  **One thing to know before item 9's sibling question comes up: Remotive's API has quietly
  become a stub.** `search=python`, `search=developer`, `search=zzqqxxnonsense`, `category=…`
  and `limit=100` all return the **same 18 jobs**, with `job-count: 18` — it now answers its
  entire feed to every query and ignores every parameter. `seen` is right about it and the alarm
  is right to stay quiet (the board *is* answering), but the crawl spends one request per search
  term — nineteen on the default profile — to be handed the same eighteen jobs nineteen times.
  → **Confirmed a second time on 2026-09-23 and now fixed.** The re-probe added the two
  questions the first one had not asked, and both sharpen it: the **bare URL** — no parameters
  at all — returns the identical eighteen ids as every query, and the payload's own
  **`total-job-count` is 18**, so this is not "search is ignored" but "the public feed is
  eighteen jobs", and there is nothing a request could ever narrow towards. Reading the
  response also turned up the part that makes this more than an efficiency note: the
  `0-legal-notice` the board sends with every answer asks for **"max. 4 times a day …
  excessive requests will be blocked"**. Nineteen terms at `SCAN_INTERVAL_HOURS = 6` is 76 a
  day. The adapter now reads the feed **once per scan** and filters on the terms in Python —
  the shape Remote OK has always had, and the reason its docstring says the feed is the whole
  board or nothing — and sends **no query parameters at all**, which is CLAUDE.md's
  unconfirmed-parameter rule applied in the direction that removes one. `seen` was tightened
  the same way item 8 tightened Kariéra's, since the loop was being rewritten anyway: it
  counts rows an id and a title could be read off, not the length of the `jobs` array, so a
  renamed field is a silent redesign the alarm can now catch. Driven live afterwards: **19
  terms → 1 request, `seen` 18 (it was 342), 7 stubs in the 7-day window**, descriptions and
  links intact. Eight tests in `RemotiveIsReadOnceTests`, **seven mutations of the shipped
  file each made to fail first** — asking per term again, `seen` back on the array length,
  counting a row before its id and title are read, counting it only once it is new, dropping
  the local term filter, dropping tags from the haystack, and swallowing a failed fetch so a
  dead board reads as an empty one. 509 tests, ruff clean.

  **Still Oliver's, and still the whole of this item's verify:** a scheduled scan on the box
  reaching `done`, every board non-zero *there*, and the worker's memory watched against its
  1500m limit while an aarch64 Chromium is up.
- [ ] **9. A real mail relay.** `DEPLOY.md §7` — a transactional relay, never the box itself.
  **Verify:** `digest --status`, then `--dry-run`, then one real `--force` send to a real
  inbox; it arrives, it is **not** in spam, and SPF and DKIM both show `pass` in the received
  headers. That is the half a socket on 127.0.0.1 could never cover.

  → **The box-free half landed 2026-09-23: the socket on 127.0.0.1, which turned out to
  cover rather more than this item assumed.** `tests/test_digest.py` replaces `mail.send`
  with a recorder, so in the whole of Phase 8 nothing had ever built an `EmailMessage` and
  put it on a wire — every TLS mode, the credentials, the envelope and every byte of the
  message were untested. `tests/test_mail.py` now carries a real SMTP server (EHLO,
  STARTTLS, AUTH LOGIN/PLAIN, MAIL FROM, RCPT TO, DATA, on a throwaway certificate) and
  asserts against **what arrived**, never against the message object. Driving it found
  three defects and a fourth on the way past:

  - **No `Date` and no `Message-ID` on any message this app has ever sent.** Neither
    `EmailMessage` nor `smtplib.send_message` writes one. `Date` is one of the two headers
    RFC 5322 makes mandatory and a missing `Message-ID` is on Gmail's own list of what a
    bulk sender must not do — and the reason it would never have been caught here is that
    most relays silently add both, so "it arrived" proves nothing about the next relay.
    Both are written now, the `Message-ID` domain being `MAIL_FROM`'s, plus
    `Auto-Submitted: auto-generated` (RFC 3834) so an out-of-office cannot bounce back at
    a bot address.
  - **The bodies went out 8-bit under an envelope that never declared it.** `set_content`
    defaults to `Content-Transfer-Encoding: 8bit`, and `send_message` adds `BODY=8BITMIME`
    **only when an address needs UTF-8** — measured: `MAIL FROM:<bot@jobmatch.app> size=551`
    and 15 bytes over 127 in the DATA. A relay without the extension may strip the high bit
    or refuse the message, and every second Slovak title carries an á. Both parts are
    `quoted-printable` now: **zero bytes above 127 on the wire**, and the accents decode back
    intact (`Senior Python vývojár`, `Košice · plný úväzok`).
  - **Credentials were handed to an unencrypted socket without complaint.** With `SMTP_SSL`
    and `SMTP_STARTTLS` both off, the sink recorded `AUTH ('bot@jobmatch.app', 'hunter2')
    encrypted=False`. `_transport` now asks the *socket* — `isinstance(smtp.sock,
    ssl.SSLSocket)`, the fact rather than the intent — and refuses, with
    `SMTP_ALLOW_INSECURE_AUTH` as the named escape hatch for a loopback relay.
  - **EHLO was the machine's name, which in a container is not a name.** `socket.getfqdn()`
    there is a dotless 12-hex hostname, and smtplib replaces that with a bare address
    literal — measured, `[147.232.182.236]` from this laptop, which would be `[172.18.0.4]`
    on the box, in every relay's log, on every message. It is `MAIL_FROM`'s domain now
    (`MAIL_DOMAIN` overrides), so the name we give, the `Message-ID` and the From: domain
    are one answer.

  Two things were already right and now have a test rather than an assumption: the
  **envelope sender is the From: address** (SPF authenticates the envelope, DMARC then asks
  whether it aligns), and the relay's **certificate is verified** — an untrusted one raises
  and sends nothing, which is the test that proves verification is on. So is header
  injection through the recipient address, which `policy.default` already refuses.
  **Nine mutations of the shipped files, each made to fail first**, including the digest's
  own ordering: marking the jobs before the send instead of after is caught by a sink that
  answers `550` to DATA. 501 passed / 12 skipped (from 483), ruff clean. `.env.example`
  gained both new variables — found by item 5's guard, which failed the moment they did not.

  **Still Oliver's:** the relay account, SPF and DKIM in real DNS, and whether a real inbox
  files it under Primary or Spam.
- [ ] **10. The live link.** `README.md`, `landing.html` and `PROJECT.md` all currently say
  there is no box; the CV bullets below say "built and deployed" and are one sentence short of
  true. **Verify:** the URL in the README opens the landing page on a phone off wifi; one tap
  on the demo button signs a stranger in cold; and the nightly reset has put it back the next
  morning.

## Phase 10 — What is worth doing while the box is pending (planned 2026-09-25)

**Phase 9 is still the ship line and still takes precedence.** Items 4–10 of it are blocked on
one thing only — an Oracle A1 instance and a DuckDNS subdomain — and every half of them a
machine without a box could do has landed (items 4, 5, 6, 7, 8, 9, plus item 8's own parked
Remotive follow-up). The moment the box exists, Phase 9 resumes and this phase waits. This
exists because "blocked" had come to mean "nothing to do", and that is not the same sentence.

It is planned against the roadmap's own standing instruction — Phase 8 said to plan the
`## Later` bucket *against a deployed thing* — and that instruction is knowingly overridden,
for the two items below that are **not** about a deployed thing. Item 1 is a defect in the
shipped image that is live today and measured. Item 3 is about the tree, not the box. Items 2
and 4 reduce what the first box session has to discover. Nothing here speculates about how a
deployment will behave in production, which is the thing Phase 8 was right to refuse.

- [x] **1. The login rate limit does not hold, and it is the shipped image that breaks it.**
  This has been in `## Later` as "in-memory and per-process — honest for one gunicorn worker,
  wrong for two", filed as the day the web tier scales. The web tier already scaled:
  `Dockerfile`'s `CMD` ships `--workers 2` and `config.RATELIMIT_STORAGE_URI` defaults to
  `memory://`, so each worker counts its own bucket. Measured through Caddy on the real stack
  during Phase 9 item 3: **30 CSRF-valid POSTs against `/login`'s `10 per minute` got 20
  through before the first 429.** `/login` is the brute-force surface, `CLAUDE.md` lists rate
  limits on the credential endpoints as a safety convention, and the limit is not just doubled
  but *non-deterministic* — which worker a request lands on decides whether it counts.

  **The fix is one process, not a shared store** (decided 2026-09-25): `--workers 1 --threads N`.
  The web tier is I/O-light — scanning lives in the worker container, and the one CPU-bound
  request is a CV upload parsing a PDF inline, which is what the generous `--timeout 120` is
  already for — so threads keep the "one slow request away from looking down" property the
  Dockerfile comment gives as the reason for two workers, and make the in-memory limiter
  correct by construction rather than by a fifth container. `RATELIMIT_STORAGE_URI` stays
  exactly where it is for the day a second process is genuinely wanted; redis was considered
  and declined, since `CLAUDE.md` already refuses that dependency for scheduling and a 12 GB
  Always Free box is not short of anything a redis would buy.

  **Threads change what the process has to be safe about, and that is the real work here** —
  `--workers 2` was declared safe in Phase 4 on the grounds that scan state lives in the
  `scans` row rather than a module global, which is an argument about *processes* and says
  nothing about two requests inside one. Three things to settle rather than assume:
  `db._ENGINES` is a plain module-level dict populated on first use, so two threads can race
  to create an engine (SQLAlchemy engines and pools are themselves thread-safe; the cache
  around them is what is not); the default `QueuePool` is `pool_size=5 / max_overflow=10`, so
  15 connections is the real concurrency ceiling and `N` must be chosen against it, not
  against the CPU count; and `app._deployed` is set once at import by `wsgi.py`, which is
  fine, but it should be *checked* to be the only mutable module state on a request path.

  **Then make the combination unable to come back.** The limiter's correctness now depends on
  a number in a `CMD` string that nothing reads — exactly the shape of defect Phase 9 kept
  finding. gunicorn honours the `WEB_CONCURRENCY` environment variable for its default worker
  count (**confirm this against the gunicorn in the image before building on it** — it is not
  installed on this laptop, so it has not been checked here); if it does, set the count there
  instead of in `CMD` and have the app refuse at boot when `WEB_CONCURRENCY > 1` and the
  storage URI is still `memory://`, alongside the two startup refusals `test_firstboot.py`
  already guards. If it does not, a test asserting the shipped `CMD` is single-process while
  the default storage is in-memory is the fallback, and worth less.

  **Verify:** the Phase 9 item 3 measurement re-run unchanged on the four-container stack
  through Caddy — 30 POSTs to `/login`, and the 11th is a 429, not the 21st; the app still
  serves a slow request and a second concurrent one (the property two workers were bought
  for); and the new refusal is **made to fail before it is trusted**, by setting
  `WEB_CONCURRENCY=2` against `memory://` and watching `up --wait` exit non-zero.

  → **Landed 2026-09-25, and every clause was measured on the four-container stack** (built
  from this tree, `DOMAIN=localhost` + `local_certs`), not reasoned about.

  `Dockerfile`'s `CMD` is now `--threads 8` and passes **no** `--workers`, so gunicorn takes
  the count from `WEB_CONCURRENCY` — `default = int(os.environ.get("WEB_CONCURRENCY", 1))`,
  read out of **gunicorn 26.2.0 in the image**, which is the assumption the item flagged as
  unverified and is now confirmed rather than assumed. The container shows one master + one
  `gthread` worker. **8 is chosen against the pool, not the CPU count**: every request holds
  exactly one `g.db` connection for its life and the default `QueuePool` is 5 + 10, so 15 is
  the ceiling — asserted in a test that reads the live pool, and made to fail at 32 threads.

  **The measurement, both ways on one stack.** Shipped config: 30 CSRF-valid POSTs to
  `/login` through Caddy, first 429 at **#11**, 10 through. Then the *old* `CMD`
  (`--workers 2`) re-run on that same stack — because a number with nothing to compare it to
  proves nothing — gave **20 through, first 429 at #15**, not #11 and not #21: the
  non-determinism the item was really about. That run also demonstrates *why* the count had
  to leave `CMD`: with `--workers 2` in the command and `WEB_CONCURRENCY` still 1, the new
  refusal saw nothing wrong and the container booted happily.

  **The property two workers were bought for survives, and the check can fail.** A request
  whose body dribbles in over 6 s holds a thread; a concurrent `GET /healthz` answered in
  **0.04 s**. The same script against a deliberately single-threaded `--workers 1` waited
  **4.71 s** — blocked until the slow request finished.

  **The refusal was made to fail before it was trusted.** `WEB_CONCURRENCY=2` against
  `memory://`: `docker compose up -d --wait web` exited **1** with `web is unhealthy`, and
  the container log carries the RuntimeError naming both values. Five unit cases pin the
  boundary (2 + memory refused, refused on loopback too since this is not about exposure,
  1 + memory is the shipped case, 4 + `redis://` accepted, limits disabled accepted).

  **Threads made module state a live question, which is the half `--workers 2` never had to
  answer.** `db._ENGINES` was a plain dict: 8 threads racing through a barrier built **8
  separate engines** in 12 runs out of 12, i.e. 8 QueuePools of 5+10 behind a thread count
  chosen for one — now double-checked under a lock, 12/12 green, with the fast path still a
  bare dict read. `auth._DUMMY_HASH` races too and is left unlocked **on purpose** (both
  threads produce a valid hash of the same string, and the function's whole job is to spend
  that time). `app._deployed` and `obs._configured` are boot-path only. Suite 509 → **519
  passed / 12 skipped**. `PROJECT.md`, `README.md`, `DEPLOY.md` and a new `CLAUDE.md`
  invariant were corrected in the same pass, since this change is what made them false.

- [ ] **2. Measure the crawl's memory curve under the worker's own limit.** Phase 9 item 4
  proved an aarch64 Chromium *starts* inside the image under `--memory=1500m --shm-size=512m`
  and rendered a page; it said in the same breath that "the crawl's real memory curve is still
  unmeasured", and item 8 owns the measurement on the box. Half of that is not actually about
  the box: a 1500m cgroup limit is the same 1500m here, and a Profesia crawl that peaks over
  it on this laptop would peak over it on Ampere too. What this laptop cannot answer is
  *speed* on 2 OCPU, and it should not pretend to.

  Run a real crawl — the default profile, the full 7-day window, every enabled board, Chromium
  up for the Profesia and Jobs.cz legs — inside the image under the worker service's own
  compose limits, sampling RSS rather than reading a single number at the end, because the
  question is the peak and a browser's peak is not where it finishes. The known risk is
  `shm_size`: Chromium in a container dies on a small `/dev/shm` in a way that reads as a
  crash rather than an OOM, which is why the item-8 text says a Chromium that dies there is a
  limit question and not a missing browser.

  **Verify:** a full crawl completes inside the container with peak RSS recorded against the
  1500m limit, with the headroom stated as a number; and the limit is **shown to be the thing
  that binds** by re-running one Playwright board under a deliberately low `--memory` and
  watching it fail — a headroom figure from a limit that could never have been hit is not a
  measurement. Whatever the number, Phase 9 item 8 still owns the box.

- [ ] **3. A document may not assert a count the tree can contradict.** Phase 9 item 3 re-read
  every claim in `PROJECT.md` against the tree on 2026-09-12 and corrected four numbers. Eleven
  days later three of them are wrong again: it says **433 tests** (the suite runs **519 passed
  / 12 skipped** as of item 1's ten new cases), it says Built covers "Phase 8 plus the first two items of Phase 9" (items 1–3
  are done and six box-free halves have landed since), and `## Later` still carries "`IDEA.md`
  is still empty, and only Oliver can fill it" — which commit `6ed3dfe` made false. Correcting
  them by hand is a day's accuracy; the item worth doing is the one that stops the recurring
  edit, since this is now the second pass over the same sentences.

  Every stale claim so far has been a **count**, and a count is the kind of assertion a command
  can answer: the test total, the adapter total (the registry, not the folder — `base.py` is
  not one, which item 3 got wrong in the other direction), the job-pool row count, the page
  count. A checker that scrapes those four out of the docs and compares them against the tree
  turns the staleness into a red run. Deliberately **not** in scope: prose claims, decisions
  and rationale — those are what `PROJECT.md` is for, a checker cannot judge them, and trying
  would produce a test that gets deleted.

  **Verify:** the checker is green on the tree only after the three stale claims above are
  corrected, and is **made to fail before it is trusted** — edit one number in `PROJECT.md` and
  one in `README.md` and watch it name both the file and the claim; then wire it into CI, since
  a checker nothing runs is a file nobody opens.

- [ ] **4. The EU-remote reach leak, which only more boards can close.** `## Later`: `remoteok`
  and `remotive` cannot be geo-narrowed at all, so a European user's remote reach is whatever
  those feeds happen to carry. Phase 8 named three candidates, shipped `jobscz`, and refused
  `nofluffjobs` and `startup.jobs` **on their own robots.txt**, verified live — that refusal
  stands and is not to be revisited. It also left a mark worth reading as a spec: PLN, GBP and
  CHF have conversion rates in `salary.EUR_RATES` and **no jobs**, because the two boards that
  would have brought PLN and GBP are exactly the two that were refused.

  So this is a sourcing question before it is a coding one, and the sourcing half is the item:
  find candidates, check `robots.txt` and the terms **first**, probe the feed live, and write
  down what each one is refused or accepted for — a board rejected politely and recorded is
  worth as much here as one that ships, which is the lesson of the two above. Adding one is
  then the one-file change `CLAUDE.md` describes, plus the two places a new board is easy to
  forget: `db.DEFAULT_SETTINGS` and `places.SOURCE_DEFAULT`. `ctx.seen()` must count rows the
  parser could *read*, the way Kariéra and Remotive were both corrected to, and the board's
  own rate-limit ask must be read out of its responses rather than assumed — Remotive's lives
  in a `0-legal-notice` field nobody would have looked for.

  **Verify:** each candidate's `robots.txt` verdict recorded with the line it turns on; at
  least one adapter driven live through a real `ScanContext` with its `seen` count cross-checked
  against the board's own stated total, not against a fixture; and the new rows land with a
  country packed into `jobs.countries`, so the reach the board was added for is actually
  reachable by the filter and the scorer.

## Off-roadmap — the role component (built 2026-09-10, verified and recorded 2026-09-12)

Not planned in any phase: it was built directly, outside the roadmap, and sat uncommitted
and unrecorded for two days — no roadmap item, no changelog line, no claim row. It is written
down here because a scoring change of this size vanishing into a working tree is the same
failure Phase 9 item 1 existed to fix, and because `CLAUDE.md` now carries two new invariants
that nothing in the plan explains.

**What it is.** A fifth scoring component, `role`, which reads `jobs.title` — the one field
every posting has and the first thing a human reads — plus a floor under the skills
denominator (`config.MIN_SKILL_EVIDENCE = 3`). The other four components could not tell what
a job *was*: a description mentioning one skill gave `skills` a perfect 1.0, and the title
was not read at all. Default weights move from four summing to 1 to five summing to 1
(`skill` .3, `role` .25, `worktype` .2, `location` .15, `seniority` .1); an account that
predates it keeps its four stored weights and picks `role` up from `DEFAULT_SETTINGS`, since
`get_all_settings` merges defaults *under* stored rows — so no backfill, and nothing
renormalizes because `score_job` divides by the weight it actually used.

- [x] **Verified against the live 7 970-job pool**, read-only through a `.backup()` copy under
  `DATA_DIR=<scratch>`, scoring every row both ways rather than trusting the write-up.
  **The old top of the list was entirely junk, all tied at a perfect 100**: "junior actuarial
  reporting analyst", "werkstudent künstliche intelligenz", "pre-sales engineer (campania)",
  "identity & pam security engineer". The new top is "lead software engineer — python",
  "lead react native engineer", "web frontend engineer — js, css, react". Perfect-100s go
  **83 → 0** for user 1 and **32 → 0** for user 3; above-threshold 2447 → 2101.
  The story `CLAUDE.md` tells is literally true and was checked row by row: job 2980 is
  `junior esg consultant (m/f)` with exactly one extracted skill, `html`, and it scored
  **100.0 for both users** before and 20.5 / 50.2 after. The documented extraction rates hold
  to the decimal — one skill in 426 of 3 454 described jobs (12.3 %, "~12 %") and none in
  1 421 (41.1 %, "~41 %").
  **Each half does most of the work independently**, which the write-up did not say: role
  alone takes user 1's perfect-100s 83 → 9, the skills floor alone 83 → 2, together 0. The
  floor is what breaks the ties; the role component is what fixes the ranking.
- [x] **Mutation-tested, and three of six mutants survived** — so the 19 new tests were not
  vacuous, but they were incomplete in exactly the places `CLAUDE.md` states as invariants.
  Killed rather than waved through, +3 tests (433 → 452 → **455 passed / 12 skipped**):
  - **A role miss returning `None` instead of `0.0` passed the whole suite.** The existing
    test asserted `role == scoring.ROLE_MISS`, which compares the constant with itself and
    stays green when it is redefined. Measured consequence: with `ROLE_MISS = None` the miss
    is *excluded* from the weighted mean and "junior esg consultant" scores **100.0 —
    identical to "junior react developer"**, the precise bug the component exists to fix.
    Now pinned against the literal `0.0` and against the two jobs not tying.
  - **Not stripping `ROLE_LEVEL_WORDS` passed too.** The existing test used "junior",
    "graduate", "student", none of which match a discipline word either way. "trainee" does:
    it contains **"ai"**, one of the words `data` is written with, so a person searching for
    trainee roles would be classified a data specialist and every "AI Engineer" in the pool
    would jump a rung.
  - **Dropping `search_terms` from `RESCORE_KEYS` passed.** `app.py`'s own comment says
    editing it must re-score — the field is two settings in one, telling the crawl what to
    fetch *and* the scorer which disciplines the user wants — and nothing tested it, so
    saving Settings could change what "frontend" means and leave every score stale.
  All six mutants now fail; `jobmatch/scoring.py` and `app.py` restored byte-identical
  afterwards, `ruff check` clean.

**Left undone on purpose:** not committed (this repo's rule is that Oliver commits), and
`CLAUDE.md`'s "77 jobs tied at 100" is a historical measurement — the same count is 83 today
against a pool that has grown from 6 842 to 7 970, so it was left as written rather than
churned into a number that goes stale again with the next scan.

## Asked for directly on 2026-10-03 (after the eligibility cut landed the same day)

Two items, written as a checklist. The first two thirds of item 1 shipped; the last third was
deferred by the person who asked for it, with its decisions already taken.

1. ~~**Filter out senior jobs.**~~ Shipped earlier the same day as `scoring.ineligible` +
   `strict_match`, and verified against the live pile: 3 of 94 rows are cut on level.
   **Still open, and it is one checkbox, not code:** `strict_match` is `False` in the live
   database, so none of the three cuts is firing. Turning it on today empties the review pile
   — 61 cut as another trade, 30 as out of reach, 3 as a level above — because **there is not
   one Košice row and not one remote row in those 94**. That is a true statement about the
   pool and the real finding under this item: the crawl's terms are broad enough to fill the
   list with nationwide brigade ads and narrow enough to find nothing in his own town. Fixing
   *that* is worth more than any further scoring work.
2. ~~**Push the student / graduate titles through.**~~ `scoring.entry_level` shares the role
   ladder's last rung, which is what carries such a title past the field cut — see `CLAUDE.md`.
3. **Then AI for the % match** — *deferred 2026-10-03 by Oliver, not dropped.* The decisions
   were taken when it was deferred, so they do not need re-deriving: **Haiku 4.5**, and the
   number sits in a **new `user_jobs.ai_score` (+ `ai_reason`) beside `match_score`**, sorting
   the list when present and falling back to the formula when absent — never overwriting it,
   because the digest, the dashboard counts, the threshold and the "matched" clause all read
   `match_score`, and a failed API call must cost one sort, not a job's score. It runs after
   the cheap filters, over what survives them (~7–20 rows a scan, so cents), with the CV in a
   cached prompt prefix. Gated on `ANTHROPIC_API_KEY` being present, inert without it, exactly
   as the digest is gated on an SMTP host.
4. ~~**One button that declines everything you did not mark.**~~ `POST /api/jobs/decline-rest`
   plus its undo — see `CLAUDE.md` for why it reuses the list's own filters.

## Later (post-launch — deliberately unplanned)

Phase 8's instruction stands: plan these against a deployed thing. Kept here so they are not
re-derived from scratch. **Emptied on 2026-09-25** — the bucket held three bullets and none of
them survived being re-read:

- ~~Rate-limit storage is in-memory and per-process.~~ **Promoted to Phase 10 item 1.** It was
  filed as "wrong for two workers, on the day the web tier scales"; the shipped `Dockerfile`
  already runs two, so it stopped being a future item the moment that `CMD` was written.
- ~~`remoteok` and `remotive` cannot be geo-narrowed, so the EU-remote reach leaks.~~
  **Promoted to Phase 10 item 4.** This one genuinely wanted a deployed thing, and still does
  for the *judgement* — whether the reach is thin is a question for a real user with real
  scores — but the sourcing half (robots.txt, terms, a live probe) needs no box and is the
  half that gates the other.
- ~~`IDEA.md` is still empty, and only Oliver can fill it.~~ **False since `6ed3dfe`**, which
  filled it with the original itch. It is one line under its placeholder comment rather than
  the paragraph the placeholder asks for, which `PROJECT.md` already says in its rough edges —
  so it is recorded in one place instead of two.


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


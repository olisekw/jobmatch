# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**JobMatch** — a multi-user web app that scans Slovak + international job boards on a schedule,
scores every offer 0–100 against each user's CV and preferences, and tracks where they applied.
It began as a single-user local tool and is now built to be deployed: real accounts, a Postgres
container, TLS via Caddy, and a public landing page with a seeded demo account.
`README.md` is detailed (board list, architecture, scoring formula, pages, full layout) —
read it first. `ROADMAP.md` has the plan and what is left.

## Commands

```bash
pip install -r requirements.txt
playwright install chromium        # needed by the Profesia.sk board, and by Jobs.cz for
                                   #   the ~30% of its ads on employer microsites
python3 app.py                     # → http://127.0.0.1:8000 (also runs the scan worker
                                   #   in-process, unless SCAN_IN_PROCESS=false)
python3 -m jobmatch.worker         # the scan worker on its own — how a deployment runs it

python3 -m jobmatch.setpassword    # set a password on an account, or create the first admin
                                   #   (prompts; or JOBMATCH_PASSWORD=… for scripts)
python3 -m jobmatch.backfill       # idempotent backfill + one-time migrations for live DBs
                                   #   (Phase 4: rebuilds `scans` so it accepts `queued`)
python3 -m jobmatch.migrate_csv    # one-time import of legacy data/*.csv (read-only towards CSVs)
python3 -m jobmatch.reextract      # replay extraction + placement over stored rows after a
                                   #   pattern fix (dry run; --apply to write, then re-scores)
python3 -m jobmatch.demo           # create or re-seed the public demo account (--status to ask)
python3 -m jobmatch.digest         # send every email digest that is due
                                   #   (--status / --dry-run / --user … --force)
python3 tools/screenshots.py       # regenerate static/screens/* for the landing page and README

python3 -m pytest tests/           # or: python3 -m unittest discover -s tests -t .
```

Python 3.9+, Flask, SQLAlchemy Core over SQLite locally and Postgres 16 in the deployment.
The database is the single source of truth and is **git-ignored**.

## Architecture

Flask app serving server-rendered pages (black & white, vanilla JS) + a JSON API. Flow:
**queue a scan → worker scans boards → extract structured fields → score → serve/filter → track applications.**

- `app.py` — Flask: pages + JSON API + auth routes. It queues scans; it never runs one.
- `jobmatch/worker.py` — the only process that scrapes: claims queued scans, reconciles
  orphans, schedules the shared crawl, sends the due digests, and resets the demo. Its own
  container in a deployment.
- `jobmatch/auth.py` — argon2id hashing, credential rules, the Flask-Login `User`. No routing
  in it, so `jobmatch.setpassword` and the tests can use it without the web app.
- `jobmatch/demo.py` — the seeded public demo account, its limits, and its nightly reset.
- `jobmatch/digest.py` — the email digest of new matches: what goes in one, the per-user
  schedule, and the wording. `jobmatch/mail.py` is the SMTP transport under it and the only
  module that opens a socket to a mail server; it knows nothing about jobs.
- `jobmatch/obs.py` — logging (text or one JSON object per line) and optional Sentry, shared
  by both entrypoints so `web` and `worker` cannot describe themselves differently.
- `config.py` — everything read from the environment, plus code-level constants (regex
  patterns, polite delays, presets).
- `jobmatch/db.py` — schema: `users`, `jobs` (including the derived `country`/`countries`), `user_jobs`
  (including `digested_at`), `user_settings`, `applications`, `application_events`, `scans`
  (which is also the scan queue).
- `jobmatch/extract.py` — regex extraction of skills / worktype / seniority / employment type.
- `jobmatch/scoring.py` — weighted match scoring + `rescore_user` / `rescore_all_users`.
- `jobmatch/scan.py` — the queue (enqueue/claim/status/cancel/reconcile) and the scan itself
  (live progress, cancel; launches a browser only when a Playwright board is enabled).
- `jobmatch/dates.py`, `salary.py`, `resume.py` — freshness→"days ago", salary→≈hourly, PDF→skills.
- `jobmatch/places.py` — a board's location text + which board it is → the country codes it
  names, stored at insert time because the Jobs page filters on them: `jobs.countries` is the
  packed set every question about *reach* is asked of, `jobs.country` the one a card prints.
  One derivation (`codes()` → `primary()`), so the two cannot disagree. It also owns
  which countries a region contains, and so the one answer to "can this person work there?"
  (`reachable_codes`) and its mirror image, "what can one request fetch for all of them?"
  (`covering_region`, which is what lets the crawl narrow itself).
- `jobmatch/sources/` — one adapter per board over `base.JobSource`; registry in `sources/__init__.py`.
- `templates/`, `static/` — the UI, including `landing.html` (the logged-out `/`) and
  `static/screens/` (the screenshots, regenerated by `tools/screenshots.py`).

## Key invariants (don't break these)

- **Scoring is over *known* components only:** `score = 100·Σ(wᵢ·cᵢ)/Σ(wᵢ)` — jobs with unparsed
  seniority/worktype are **not** punished for missing data. Jobs with no fetched description are
  shown unscored until the next scan. The UI says so too: an unknown component is a *hatched*
  bar, never an empty one, because an empty bar reads as a zero.
- **"Matched" is always derived** (`score ≥ threshold` and status `new`), never stored — changing
  weights/threshold in Settings re-scores instantly and throws nothing away.
- **A source's structured fields beat regex extraction** — if a board's API gives `posted_at`,
  `salary_min/max`, `worktype`, `seniority`, carry them through; only fall back to `extract.py`.
  Each adapter declares these in `JobSource.provides`; keep it in sync with what the adapter
  actually sets, because once stored the two are indistinguishable, and both `reextract.py`
  **and the scan's enrich phase** rely on that declaration to know which columns they must
  not overwrite — a board with a detail page reads its description *after* its card, so
  without it the prose silently erases what the card stated.
- **Adding a board = one file** in `jobmatch/sources/` implementing `search(page, terms, days,
  known_ids, ctx)` (+ `fetch_detail()` if listings lack descriptions) + a registry entry. Set
  `needs_browser = True` only if the site requires Playwright.
- **Migrations are additive and idempotent** (`backfill.py`) — never touch a user's statuses/scores.
  `init_schema` can add a column but not change a CHECK constraint; anything that alters one
  needs a table rebuild in `backfill.py` (see `migrate_scan_queue`) and a check at boot.
- **Scanning lives in the worker, and `scans` is the queue.** No scan state in module globals:
  a status poll must be answerable by a process that is not scanning. Triggering is admin-only
  and the crawl is global — one scrape serves every user, or the boards ban us.
  The crawl's terms, boards and window are the **admin's** settings; *where* is the one thing
  that is not, because their answer is not the other accounts'. `db.crawl_regions` is the
  union of every account's reach, handed to adapters as `ctx.regions`, and **one user nobody
  can place empties it** — a narrowed crawl never fetches what it did not ask for, and the
  shared pool is the only place a score can come from. Narrowing may only ever be an
  optimisation: one geo or none, never a second pass over the same board, and never a
  parameter that has not been confirmed against the live API (Remotive and Arbeitnow accept
  unknown ones and answer as if they were absent).
- **Scheduling is a query, not a timer.** The scan schedule, the demo reset and each user's
  digest all ask "is the last one older than the interval?" — it survives a restart, cannot
  drift and cannot double-fire. Don't reach for APScheduler, Celery or Redis.
- **A job is emailed at most once, and that is a stored fact.** `user_jobs.digested_at` records
  what actually went out, because a job that crosses the threshold only when the user moves a
  weight *is* news and no comparison against `scraped_at` would ever notice it. The digest
  selects on the same "matched" clause the dashboard counts with, plus `digested_at IS NULL` —
  the email and the Jobs page must never disagree about what counts. The run is stamped
  *before* the send (a dead relay costs one cycle, not a retry every poll) and the jobs only
  after it, so a failed send loses nothing and everything arrives next time.

- **Words for stored values live server-side, and so do groupings of them.** `display.py`
  owns every label; `display.APPLICATION_GROUPS` owns the tracker's tabs (which is why
  "Waiting to hear" is two statuses in one tab) and `places.LABELS` owns country names. A
  page renders what `/api/settings` hands it — the tab, the chip and the filter that hides
  the chip cannot then word the same fact three ways.
- **Remote is a work permit, on-site is a commute.** One component, two rules, because
  "remote" changes what location means: on-site/hybrid match the town, remote intersects
  `jobs.countries` with `places.reachable_codes()` over the user's `user_regions`. A remote
  job is *not* automatically a 1.0 — that was the bug. An unplaced row stays `None` (hatched,
  never a zero) and so does a user who has answered nothing, which `db.user_regions` derives
  from their town rather than defaulting everybody to Europe.
- **A posting hiring in five places names five places.** One column cannot hold five answers,
  and first-match-wins stored "LATAM, Europe, USA, Canada, APAC" as `US` — unreachable for a
  European though it says Europe out loud. So `places.codes()` returns them all, packed into
  `jobs.countries` (`|EU|US|CA|`, delimited both ends so `|US|` cannot match inside another
  code), and `places.primary()` picks the one `jobs.country` prints: the specific one when
  the places all sit inside one region ("Berlin — Europe" is a German job), the widest when
  they do not. **Reach is a question about the set**, asked identically by the scorer
  (`places.stored_codes`) and by the filter (`places.COUNTRIES_SQL`, which falls back to
  `country` so a row is right the moment the column is added, not the moment somebody
  backfills). `backfill.migrate_countries` packs old rows; `jobmatch.reextract` replays a
  table fix over all of them.
- **A filter selects on a column, never on prose.** Work mode is `jobs.worktype`, country is
  `jobs.countries` (with one pseudo-value, `reachable`, expanded through the *same*
  `places.reachable_codes()` the scorer uses, so the list and the score cannot disagree about
  where you can work), pay is `salary.HOURLY_EUR_SQL` over the structured salary columns — the
  same conversion the card prints, generated from `salary.HOURS_PER` *and* `salary.EUR_RATES`
  so the number you filter on and the number you read cannot drift. A filter value the server
  does not recognise is ignored rather than obeyed, so a hand-edited query string cannot empty
  the list.
- **Comparing two salaries takes one period and one currency.** A board's amount, currency and
  period are stored exactly as written and `salary.range_display` reads them back that way;
  the comparison is derived on the way out, in euros an hour, by `salary.hourly_eur()` and its
  SQL mirror. Per-hour alone was half an answer — it made a monthly Slovak wage and an annual
  American salary comparable and still ranked 140 000 Kč level with 140 000 €. The rates in
  `salary.EUR_RATES` are approximate and dated on purpose: nothing stored reads them, so
  refreshing them rewrites no row and moves no score. A currency with no rate is **unknown,
  not par** — it sorts last and fails a floor, exactly like a posting that quotes nothing,
  because a euro figure for a wage nobody quoted in euros is worse than no ranking at all.

## Conventions & safety

- **Multi-user as of Phase 3**: argon2id + Flask-Login sessions, CSRF on every mutating route,
  rate limits on the credential endpoints. Every route is behind `@login_required` and every
  query is scoped by `current_user_id()` — adding a route means doing both. The two deliberate
  exceptions are `/` (the landing page, which branches on `current_user.is_authenticated`) and
  `/healthz`; both are public on purpose and neither reads a user's data. The job pool in
  `jobs` is the one thing that is deliberately shared.
- **It expects to be deployed.** `SECRET_KEY` must come from the environment; startup refuses
  the dev key or debug mode on anything but a loopback bind, and `wsgi.py` calls
  `app.mark_deployed()` because gunicorn binds with `--bind` and never reads `HOST`.
  Put it behind the bundled Caddy for TLS — see `DEPLOY.md`.
- **The demo account is a real account with three holes punched in it**: no CV upload, no
  self-deletion, and never an admin (which is what stops it triggering a scan). It is
  identified by email against `config.DEMO_EMAIL`, so `users` needs no column for it, and
  it is deliberately *not* read-only — the nightly reset is what makes that safe.
- Scrapers keep **polite delays** (5–16s between page requests on Slovak boards); don't remove them.
  API boards are fast; the default incremental scan window (last 7 days) keeps runs quick.
- The DB is the source of truth and git-ignored — back it up if the tracker history matters.
- Don't commit to `main` — branch first. Commit/push only when asked.

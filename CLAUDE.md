# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**JobMatch** — a local, single-user web app that scans Slovak + international job boards, scores
every offer 0–100 against your CV and preferences, and tracks where you applied. `README.md` is
detailed (board list, scoring formula, pages, full layout) — read it first.

## Commands

```bash
pip install -r requirements.txt
playwright install chromium        # only needed for the Profesia.sk board
python3 app.py                     # → http://127.0.0.1:8000 (also runs the scan worker
                                   #   in-process, unless SCAN_IN_PROCESS=false)
python3 -m jobmatch.worker         # the scan worker on its own — how a deployment runs it

python3 -m jobmatch.setpassword    # set a password on an account, or create the first admin
                                   #   (prompts; or JOBMATCH_PASSWORD=… for scripts)
python3 -m jobmatch.backfill       # idempotent backfill + one-time migrations for live DBs
                                   #   (Phase 4: rebuilds `scans` so it accepts `queued`)
python3 -m jobmatch.migrate_csv    # one-time import of legacy data/*.csv (read-only towards CSVs)
python3 -m jobmatch.reextract      # replay extraction over stored rows after a pattern fix
                                   #   (dry run; --apply to write, then re-scores)

python3 -m pytest tests/           # or: python3 -m unittest discover -s tests -t .
```

Python 3.9+, Flask, SQLite. `data/jobmatch.db` is the single source of truth and is **git-ignored**.

## Architecture

Flask app serving server-rendered pages (black & white, vanilla JS) + a JSON API. Flow:
**queue a scan → worker scans boards → extract structured fields → score → serve/filter → track applications.**

- `app.py` — Flask: pages + JSON API + auth routes. It queues scans; it never runs one.
- `jobmatch/worker.py` — the only process that scrapes: claims queued scans, reconciles
  orphans, and schedules the shared crawl. Run as its own container in a deployment.
- `jobmatch/auth.py` — argon2id hashing, credential rules, the Flask-Login `User`. No routing
  in it, so `jobmatch.setpassword` and the tests can use it without the web app.
- `config.py` — code-level constants (regex patterns, polite delays, presets).
- `jobmatch/db.py` — schema: `users`, `jobs`, `user_jobs`, `user_settings`, `applications`,
  `application_events`, `scans` (which is also the scan queue).
- `jobmatch/extract.py` — regex extraction of skills / worktype / seniority / employment type.
- `jobmatch/scoring.py` — weighted match scoring + `rescore_user` / `rescore_all_users`.
- `jobmatch/scan.py` — the queue (enqueue/claim/status/cancel/reconcile) and the scan itself
  (live progress, cancel; launches a browser only when a Playwright board is enabled).
- `jobmatch/dates.py`, `salary.py`, `resume.py` — freshness→"days ago", salary→≈hourly, PDF→skills.
- `jobmatch/sources/` — one adapter per board over `base.JobSource`; registry in `sources/__init__.py`.
- `templates/`, `static/` — the UI.

## Key invariants (don't break these)

- **Scoring is over *known* components only:** `score = 100·Σ(wᵢ·cᵢ)/Σ(wᵢ)` — jobs with unparsed
  seniority/worktype are **not** punished for missing data. Jobs with no fetched description are
  shown unscored until the next scan.
- **"Matched" is always derived** (`score ≥ threshold` and status `new`), never stored — changing
  weights/threshold in Settings re-scores instantly and throws nothing away.
- **A source's structured fields beat regex extraction** — if a board's API gives `posted_at`,
  `salary_min/max`, `worktype`, `seniority`, carry them through; only fall back to `extract.py`.
  Each adapter declares these in `JobSource.provides`; keep it in sync with what the adapter
  actually sets, because once stored the two are indistinguishable and `reextract.py` relies
  on that declaration to know which columns it must not overwrite.
- **Adding a board = one file** in `jobmatch/sources/` implementing `search(page, terms, days,
  known_ids, ctx)` (+ `fetch_detail()` if listings lack descriptions) + a registry entry. Set
  `needs_browser = True` only if the site requires Playwright.
- **Migrations are additive and idempotent** (`backfill.py`) — never touch a user's statuses/scores.
  `init_schema` can add a column but not change a CHECK constraint; anything that alters one
  needs a table rebuild in `backfill.py` (see `migrate_scan_queue`) and a check at boot.
- **Scanning lives in the worker, and `scans` is the queue.** No scan state in module globals:
  a status poll must be answerable by a process that is not scanning. Triggering is admin-only
  and the crawl is global — one scrape serves every user, or the boards ban us.

## Conventions & safety

- **Multi-user as of Phase 3**: argon2id + Flask-Login sessions, CSRF on every mutating route,
  rate limits on the credential endpoints. Every route is behind `@login_required` and every
  query is scoped by `current_user_id()` — adding a route means doing both. The job pool in
  `jobs` is the one thing that is deliberately shared.
- Still meant for a machine you control until Phase 5 puts it behind TLS: `SECRET_KEY` must
  come from the environment and `HOST` must stay on loopback otherwise (startup enforces it).
- Scrapers keep **polite delays** (5–16s between page requests on Slovak boards); don't remove them.
  API boards are fast; the default incremental scan window (last 7 days) keeps runs quick.
- The DB is the source of truth and git-ignored — back it up if the tracker history matters.
- Don't commit to `main` — branch first. Commit/push only when asked.

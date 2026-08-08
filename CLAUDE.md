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
python3 app.py                     # → http://127.0.0.1:8000

python3 -m jobmatch.backfill       # idempotent additive-column backfill for live DBs
python3 -m jobmatch.migrate_csv    # one-time import of legacy data/*.csv (read-only towards CSVs)
```

Python 3.9+, Flask, SQLite. `data/jobmatch.db` is the single source of truth and is **git-ignored**.

## Architecture

Flask app serving server-rendered pages (black & white, vanilla JS) + a JSON API. Flow:
**scan boards (background thread) → extract structured fields → score → serve/filter → track applications.**

- `app.py` — Flask: pages + JSON API + scan-thread management.
- `config.py` — code-level constants (regex patterns, polite delays, presets).
- `jobmatch/db.py` — SQLite schema: `jobs`, `applications`, `application_events`, `settings`, `scans`.
- `jobmatch/extract.py` — regex extraction of skills / worktype / seniority / employment type.
- `jobmatch/scoring.py` — weighted match scoring + `rescore_all`.
- `jobmatch/scan.py` — scan orchestrator (thread, live progress, cancel; launches a browser only
  when a Playwright board is enabled).
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
- **Adding a board = one file** in `jobmatch/sources/` implementing `search(page, terms, days,
  known_ids, ctx)` (+ `fetch_detail()` if listings lack descriptions) + a registry entry. Set
  `needs_browser = True` only if the site requires Playwright.
- **Migrations are additive and idempotent** (`backfill.py`) — never touch a user's statuses/scores.

## Conventions & safety

- **Single user, local machine, no auth — never expose it to the internet.**
- Scrapers keep **polite delays** (5–16s between page requests on Slovak boards); don't remove them.
  API boards are fast; the default incremental scan window (last 7 days) keeps runs quick.
- The DB is the source of truth and git-ignored — back it up if the tracker history matters.
- Don't commit to `main` — branch first. Commit/push only when asked.

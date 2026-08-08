# PROJECT.md — JobMatch

## Why this exists

Job hunting across Slovak + international boards means manually checking
6+ sites, eyeballing whether each posting fits, and tracking application
status in a spreadsheet. JobMatch automates the scan, scores every offer
against a personal CV/preference profile, and folds application tracking
into the same tool, all running locally against a personal SQLite DB —
single-user, no auth, not meant to be internet-facing (explicit in the
README's "Notes" section).

## Key decisions

- **Runtime settings live in the DB, not code.** `config.py` is explicitly
  scoped to code-level constants only (scrape delays, timeouts, regex
  patterns); scoring weights, match threshold, search terms, and user
  profile are all in the SQLite `settings` table, editable from the UI
  without a restart.
- **Scoring only penalizes what's known.** `score = 100·Σ(wᵢcᵢ)/Σ(wᵢ)` sums
  only over components with known data for a job, so a posting with
  unparsed seniority isn't dragged down for missing information.
  "Matched" is always re-derived from score + threshold, never stored as a
  fixed label — changing weights re-scores instantly with no re-scrape.
- **Plain HTTP/JSON APIs preferred over scraping; Playwright only where
  required.** 4 of 6 sources (`remoteok`, `remotive`, `jobicy`, `arbeitnow`)
  hit public JSON APIs; `kariera` is server-rendered HTML via plain HTTP
  (BeautifulSoup); only `profesia` needs a real browser
  (`needs_browser = True`), because it's the one dynamic site. Each source is
  a self-contained adapter (`jobmatch/sources/*.py`) behind one `JobSource`
  interface, so adding a board is additive (new file + registry entry).
- **Polite scraping by design.** 5.5–16s randomized delays between
  page/detail requests on the Slovak boards specifically (API boards aren't
  throttled) — a deliberate trade of first-scan speed for not hammering
  sites without an API contract.
- **CSV → SQLite migration path kept, not deleted.** `migrate_csv.py` and
  `backfill.py` exist as idempotent, read-only-toward-CSV one-time migration
  tools from an earlier CSV-based version of the app; legacy CSVs are kept
  as backups, not auto-deleted.
- **No FX conversion for salary.** Hourly-rate derivation divides by a fixed
  hours factor (day÷8, week÷40, month÷160, year÷1920) but keeps the original
  currency — deliberately not attempting currency normalization.

## Current state

**Built:** Flask app (`app.py`) with 4 pages (Dashboard, Jobs, Tracker,
Settings) and a JSON API; 6 working source adapters under
`jobmatch/sources/` (`profesia`, `kariera`, `remoteok`, `remotive`, `jobicy`,
`arbeitnow`) registered in `sources/__init__.py`; scan orchestration in a
background thread with live progress/cancel (`scan.py`); scoring engine
(`scoring.py`); skill/worktype/seniority extraction via regex
(`extract.py`, with an extensive `CODING_PATTERNS` list in `config.py`);
salary and date parsing (`salary.py`, `dates.py`); PDF resume parsing via
`pdfplumber` (`resume.py`); application tracking with status pipeline and
event history in `db.py`.

**Data:** `data/jobmatch.db` (SQLite, gitignored) is live and populated —
present in the working tree at ~9.7MB with WAL files, i.e. this has actually
been run and used, not just scaffolded.

**Known rough edges:**
- Single git history shows the app went through several structural passes
  ("changing structure", "new structure, better results, more columns")
  before settling — no explicit test suite was found under the repo (no
  `tests/` directory), so scoring/extraction correctness relies on manual
  verification.
- Profesia.sk scraping depends on Playwright + a real Chromium install
  (`playwright install chromium`), the heaviest dependency in the stack —
  if that site's markup changes, `profesia.py` is the most likely adapter to
  break silently.
- `.claude/launch.json` pins the run command to `/usr/bin/python3 app.py`
  directly (no explicit venv activation step recorded), so make sure
  `pip install -r requirements.txt` targets whichever interpreter that
  resolves to.

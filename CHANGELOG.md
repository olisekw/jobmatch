# Changelog — jobmatch

One line per change, newest first. The `/roadmap-task` skill appends a sentence here after
each completed roadmap task. The plan lives in `ROADMAP.md`; the rationale in `PROJECT.md`.

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

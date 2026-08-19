# JobMatch

A local web app that scans Slovak and international job boards, scores every
offer against your CV and preferences, and tracks where you applied.

![](https://img.shields.io/badge/python-3.9+-black)
![](https://img.shields.io/badge/backend-Flask-black)
![](https://img.shields.io/badge/storage-SQLite-black)
![](https://img.shields.io/badge/UI-black%20%26%20white-black)

## What it does

- **Scans 6 job boards on a schedule** — one crawl serves everyone on the
  instance, run by a separate worker process with live per-board progress and a
  cancel button; an admin can also trigger one. Each board toggles in Settings.

  | Board | Coverage | How |
  |---|---|---|
  | [Profesia.sk](https://www.profesia.sk) | Slovakia | Playwright (dynamic site) |
  | [Kariéra.sk](https://kariera.zoznam.sk) | Slovakia | plain HTTP, server-rendered |
  | [Remote OK](https://remoteok.com) | worldwide remote | public JSON API |
  | [Remotive](https://remotive.com) | worldwide remote | public JSON API |
  | [Jobicy](https://jobicy.com) | worldwide remote | public JSON API |
  | [Arbeitnow](https://www.arbeitnow.com) | EU, remote-flagged only | public JSON API |

- **Scores every job 0–100** from weighted components: skills coverage,
  worktype, location (diacritics-insensitive, remote counts as a match),
  seniority. Weights and the match threshold are sliders in Settings;
  changing them re-scores instantly — no re-scraping.
- **Shows the facts on every card** — posting age ("3 days ago"), salary with
  an approximate hourly rate ("od 2 500 eur/mesiac · ≈ 15.6 €/h"), seniority,
  remote / hybrid / onsite, fulltime / parttime, location, source and the
  detected skills.
- **Reads your CV** — drop a PDF in Settings; skills are extracted and merged
  into your profile, and everything is re-scored.
- **Tracks applications** — mark a job Applied and it enters the tracker:
  applied date, status pipeline (applied → interview → offer / rejected /
  withdrawn / no response), inline notes, and a full status-change history.

## Run

```bash
pip install -r requirements.txt
playwright install chromium        # only needed for Profesia.sk

python3 app.py                     # → http://127.0.0.1:8000
```

That also runs the scan worker in the same process, which is what you want
locally. A deployment runs it separately, so that the web tier can be several
processes while exactly one of them scrapes:

```bash
gunicorn --bind 0.0.0.0:8000 wsgi:app     # web
python3 -m jobmatch.worker                # scanning, on its own
```

Upgrading from an older database? Apply the additive schema changes, run the
one-time migrations and fill the new columns (safe, idempotent, never touches
your statuses or scores):

```bash
python3 -m jobmatch.backfill
```

First time only, if you still have legacy CSV data in `data/` (jobs.csv,
applied.csv, user.csv, resume.txt), import it:

```bash
python3 -m jobmatch.migrate_csv
```

Both commands are idempotent and read-only towards the CSVs — they stay in
`data/` as backups; delete them yourself once you're happy.

## Pages

| Page | What's there |
|---|---|
| **Dashboard** | Stat cards, last-scan summary, scan button, top matches |
| **Jobs** | Every offer with score badge + per-component breakdown (hover), filters (status / min-score slider / source / text / sort), Apply · Decline · Restore |
| **Tracker** | Applications with status dropdown, notes, event history |
| **Settings** | CV upload, profile (location / seniority / worktype / skills), score weights, match threshold, search terms & presets, board toggles, scan window |

## Layout

```
app.py                  Flask app: pages + JSON API + auth; queues scans
wsgi.py                 gunicorn entrypoint
config.py               code-level constants (regex patterns, delays, presets)
jobmatch/
  db.py                 SQLite (data/jobmatch.db): users, jobs, user_jobs,
                        user_settings, applications, application_events,
                        scans — which doubles as the scan queue
  auth.py               argon2id hashing, credential rules, the login user
  worker.py             the scan worker: claims queued scans, reconciles
                        orphans, schedules the shared crawl
  extract.py            skill/worktype/seniority/employment regex extraction
  scoring.py            weighted match scoring + rescore_user
  scan.py               the queue + the scan itself (progress, cancel,
                        browser only when a Playwright board is enabled)
  dates.py              freshness strings → posted date → "days ago"
  salary.py             salary strings → structured pay → ≈ hourly rate
  resume.py             PDF → text → skills
  setpassword.py        set a password from the shell / create the first admin
  migrate_csv.py        one-time legacy CSV import
  backfill.py           idempotent column backfill + one-time migrations
  sources/              one adapter per job board
    base.py             JobSource interface + shared HTTP/matching helpers
    profesia.py         kariera.py   remoteok.py   remotive.py
    jobicy.py           arbeitnow.py
templates/, static/     server-rendered UI (black & white), vanilla JS
```

## How scoring works

`score = 100 · Σ(wᵢ·cᵢ) / Σ(wᵢ)` over the components that are *known* for a
job, so offers with unparsed seniority/worktype aren't punished for missing
data. Jobs whose description hasn't been fetched yet are shown as unscored
until the next scan. "Matched" is always derived (`score ≥ threshold` and
status `new`) — nothing is thrown away when you change settings.

Hourly pay is derived from the parsed salary: hour as-is, day ÷ 8, week ÷ 40,
month ÷ 160, year ÷ 1920 — original currency, no FX conversion.

## Adding a job board

One file in `jobmatch/sources/` implementing `search(page, terms, days,
known_ids, ctx)` (+ `fetch_detail()` if listings don't include descriptions),
then a registry entry in `sources/__init__.py`. Stubs can carry structured
fields (`posted_at`, `salary_min/max`, `worktype`, `seniority`, …) — anything
the board provides beats regex extraction. Set `needs_browser = True` only if
the site requires Playwright.

## Notes

- Multi-user, with real accounts: sign up at `/signup`, or run
  `python3 -m jobmatch.setpassword` to set a password from the shell (this is how an
  account created before logins existed gets one). The job pool is shared by everyone
  on the instance; scores, statuses and the tracker are yours alone.
- Still meant for a machine you control — it wants a real `SECRET_KEY` and TLS in front
  of it before it is worth putting on the open internet.
- Scanning runs in its own process (`python3 -m jobmatch.worker`); `python3 app.py`
  starts one in-process so local development stays a single command. Scrapers keep
  polite delays (5–16 s between page requests on the Slovak boards), so a full first
  scan takes a while — the incremental default (last 7 days) is fast, and API boards
  respond in seconds.
- The database (`data/jobmatch.db`) is the single source of truth and is
  gitignored — back it up if you care about your tracker history.

# PROJECT.md — JobMatch

## Why this exists

Job hunting across Slovak + international boards means manually checking 6+
sites, eyeballing whether each posting fits, and tracking application status in
a spreadsheet. JobMatch automates the scan, scores every offer against a
CV/preference profile, and folds application tracking into the same tool.

It was built as a single-user local tool and deliberately turned into a
deployable multi-user one (see `ROADMAP.md`, direction set 2026-08-08). Two
things drove that change, and both are still the shape of the codebase:

1. **A tool that only runs on one laptop cannot be shown to anybody.** The
   point of the rewrite is a URL — a landing page, a demo account a recruiter
   can click into, and a deployment somebody can be told about.
2. **Scraping must not multiply per user.** Profesia.sk and Kariéra.sk are
   scraped with politeness delays and no API contract, so a scan per user from
   a cloud IP means bans. The job pool therefore stays **global**: the server
   scans once on a schedule and every user gets their own scores, statuses and
   tracker on top of the shared pool. This is both the safe answer and the
   cleaner multi-tenant design.

## Key decisions

- **Scoring only penalizes what's known.** `score = 100·Σ(wᵢcᵢ)/Σ(wᵢ)` sums
  only over components with known data for a job, so a posting with unparsed
  seniority isn't dragged down for missing information. "Matched" is always
  re-derived from score + threshold, never stored as a fixed label — changing
  weights re-scores instantly with no re-scrape. The UI carries the same idea:
  an unknown component is a hatched bar, never an empty one, because an empty
  bar reads as a zero.
- **Remote is a work permit, on-site is a commute.** The location component
  carries two rules because "remote" changes what the word means. On-site and
  hybrid are matched on the town; remote is matched on `jobs.country` against
  the set of places the user said they can work in, so a US-only remote role no
  longer scores full marks for somebody in Bratislava — which it did, ranking
  level with the EU roles it should have been losing to. The preference is its
  own setting rather than a reading of `user_location`, because "where I live"
  and "where I may work" are different questions, and it is *derived* from the
  town when unanswered (your country plus its region) rather than defaulted to
  Europe for everybody. One expansion in `places.reachable_codes()` answers it
  for the scorer, the Jobs filter and the digest at once.
- **Runtime settings live in the DB, not code.** `config.py` holds the
  environment (deployment) and code-level constants (scrape delays, timeouts,
  regex patterns); scoring weights, match threshold, search terms and the user
  profile are per-user rows in `user_settings`, editable from the UI without a
  restart.
- **The shared crawl is the multi-tenant model.** `jobs` is global; `user_jobs`,
  `user_settings`, `applications` and `application_events` all hang off
  `user_id`. Materializing `user_jobs` is one `INSERT … SELECT`, so score
  filtering and sorting stay in SQL.
- **The scanner is a separate process over a DB-backed queue.** `scans` is both
  the history and the queue: a trigger inserts a `queued` row, the worker claims
  it with a conditional `UPDATE`, and every bit of live state a status poll
  needs (phase, counters, heartbeat, cancel flag) is a column. No scan state in
  module globals, so any web process can answer "how is it going?" — which is
  what lets the web tier be several gunicorn workers while exactly one
  container scrapes.
- **Scheduling is a query, not a timer.** "Is the newest scan older than the
  interval?" survives a restart, cannot drift and cannot double-fire if a second
  worker ever exists. The nightly demo reset uses the same pattern. No
  APScheduler, no Celery, no Redis — the dependency bought nothing.
- **SQLAlchemy Core, not the ORM.** Tables are `Table` objects so DDL is
  dialect-correct and `create_all` idempotent, while every *query* stays plain
  `text()` SQL. The one real cost was paramstyle (`?` → named `:binds`) and
  reading new ids back with `INSERT … RETURNING id`.
- **Plain HTTP/JSON APIs preferred over scraping; Playwright only where
  required.** 4 of 7 sources hit public JSON APIs; `kariera` is server-rendered
  HTML via plain HTTP; `profesia` needs a real browser, and `jobscz` needs one
  for the ~30% of its ads that redirect to an employer microsite whose body is
  fetched client-side — its search is plain HTTP throughout. Each source is a
  self-contained adapter behind one `JobSource` interface, and declares which
  structured fields it provides so a board's own data always beats regex
  extraction.
- **Polite scraping by design.** 5.5–16s randomized delays between page/detail
  requests on the Slovak boards specifically — a deliberate trade of first-scan
  speed for not hammering sites without an API contract.
- **The demo is playable, not read-only.** A demo where the sliders do not move
  is a screenshot. Visitors get a real account they can triage and re-weight,
  which is safe precisely because the worker puts it back every night. Three
  things it may not do — upload a CV, delete itself, trigger a scan — and it is
  identified by email, so `users` needed no new column for it.
- **A job is emailed at most once, and that is stored, not derived.** The
  digest's `user_jobs.digested_at` is a fact about what was *sent*, because it
  has to be: a posting that crosses the threshold only when the user moves a
  weight is genuinely news to them, and no comparison against `scraped_at`
  would notice it. What goes in a digest is the same "matched" clause the
  dashboard counts with, so the email and the Jobs page cannot form two
  opinions; and the run is stamped before the send, so a dead relay costs a
  cycle of latency instead of a retry on every poll.
- **CSV → SQLite migration path kept, not deleted.** `migrate_csv.py` and
  `backfill.py` exist as idempotent, read-only-toward-CSV one-time migration
  tools from an earlier CSV-based version of the app.
- **No FX conversion for salary.** Hourly-rate derivation divides by a fixed
  hours factor (day÷8, week÷40, month÷160, year÷1920) but keeps the original
  currency — deliberately not attempting currency normalization.

## Current state

**Built:** everything through Phase 7 of `ROADMAP.md`, plus three of Phase 8's
items. A Flask app with six pages (landing, dashboard, jobs, job detail,
tracker, settings) and a JSON API;
real accounts on argon2id with CSRF, rate limits and tenant isolation; six
source adapters; a scan worker over the `scans` queue with live progress,
cancel and orphan reconciliation; scoring, extraction, salary/date parsing and
PDF CV parsing; application tracking with a status pipeline and event history;
a containerized deployment (`web`/`worker`/`db`/`caddy`) with tested backups; a
public landing page and a seeded demo account; `/healthz` and JSON logging.

**Data:** the local `data/jobmatch.db` is live and populated — 2375 jobs, used
rather than scaffolded. Every risky migration has been verified against a
`.backup()` copy of it, which is what caught the bugs unit tests could not.

**Tests:** 318, of which 12 skip themselves without a Postgres server.

**Known rough edges:**
- **There is no box.** Phase 5 is built and verified locally but no VPS or
  domain exists, so `caddy`, TLS and `deploy.yml` have never run, and there is
  no public URL. That is an account and a domain, not code.
- `IDEA.md` is still empty. It wants one honest paragraph, in the author's own
  words, on the original itch — nobody else can write it.
- Profesia.sk scraping depends on Playwright + a real Chromium install, the
  heaviest dependency in the stack, and it is still the adapter most likely to
  break. It can no longer break *silently* — Phase 8 made every adapter report
  what the board showed it before filtering, and a source that showed nothing at
  all is an ERROR on the scan row — but that alarm has never fired against live
  markup, only against fixtures. One scheduled scan on the box settles it.
- **The digest has never met a real mail relay.** It has been run end to end
  against a socket on localhost, so the code path is proven; deliverability
  (SPF, DKIM, spam folders) needs the box, like TLS.
- Rate-limit storage is in-memory and per-process, which is honest for one
  gunicorn worker and wrong for two — `RATELIMIT_STORAGE_URI` is where a redis
  URL goes if that day comes.

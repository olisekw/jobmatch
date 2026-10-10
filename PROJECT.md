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
  hybrid are matched on the town; remote intersects the places the *posting*
  names with the set of places the user said they can work in, so a US-only
  remote role no longer scores full marks for somebody in Bratislava — which it
  did, ranking level with the EU roles it should have been losing to. The
  preference is its own setting rather than a reading of `user_location`,
  because "where I live" and "where I may work" are different questions, and it
  is *derived* from the town when unanswered (your country plus its region)
  rather than defaulted to Europe for everybody. One expansion in
  `places.reachable_codes()` answers it for the scorer, the Jobs filter and the
  digest at once.
- **A posting hiring in five places names five places.** Reach is a question
  about a *set*, so it is not asked of one column: `places.codes()` returns
  every place a listing names and packs them into `jobs.countries`
  (`|EU|US|CA|`, delimited both ends so `|US|` cannot match inside another
  code), while `places.primary()` picks the single code `jobs.country` prints on
  a card. One column could not hold five answers, and first-match-wins stored
  "LATAM, Europe, USA, Canada, APAC" as `US` — unreachable for a European
  though it says Europe out loud. The scorer (`places.stored_codes`) and the
  Jobs filter (`places.COUNTRIES_SQL`, which falls back to `country`) ask the
  set the same question, so the list and the score cannot disagree about where
  you can work.
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
  what lets the web tier scale out while exactly one container scrapes. It is
  not what *decides* the shipped process count: that is one, because the
  in-memory rate limiter is per-process (Phase 10 item 1), and the scan-state
  argument is silent on limiter buckets — it says a second process would be
  correct about scans, not that it would be correct about everything.
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
- **Comparing two salaries takes one period and one currency.** A board's
  amount, currency and period are stored exactly as written and read back that
  way; the comparison is derived on the way *out*, in euros an hour, by
  `salary.hourly_eur()` and its SQL mirror `HOURLY_EUR_SQL` — one hours factor
  (day÷8, week÷40, month÷160, year÷1920) and one rate table, so the number
  the pay filter selects on and the number the card prints cannot drift. This
  reverses an earlier decision to normalize the period only, which was half an
  answer: it made a monthly Slovak wage comparable to an annual American salary
  and still ranked 140 000 Kč level with 140 000 €, and the live pool's entire
  top five was Czech on the strength of koruna's extra digits. The rates in
  `salary.EUR_RATES` are approximate and dated on purpose — nothing stored reads
  them, so refreshing them rewrites no row and moves no score — and a currency
  with no rate is **unknown, not par**: it sorts last and fails a floor, exactly
  like a posting that quotes nothing, because a euro figure for a wage nobody
  quoted in euros is worse than no ranking at all.

## Current state

**Built:** every phase of `ROADMAP.md` through Phase 8, plus the first two items
of Phase 9. A Flask app with five pages (landing, dashboard, jobs, tracker,
settings) and a JSON API; real accounts on argon2id with CSRF, rate
limits and tenant isolation; seven source adapters (`profesia`, `kariera`,
`jobscz`, `remoteok`, `remotive`, `jobicy`, `arbeitnow`); a scan worker over the
`scans` queue with live progress, cancel and orphan reconciliation; scoring,
extraction, country derivation, salary/date parsing and PDF CV parsing;
application tracking with a status pipeline and event history; an email digest
over its own SMTP transport; a containerized deployment
(`web`/`worker`/`db`/`caddy`) with tested backups; a public landing page and a
seeded demo account; `/healthz` and JSON logging.

**Data:** the local `data/jobmatch.db` is live and populated — 6842 jobs, used
rather than scaffolded. Every risky migration has been verified against a
`.backup()` copy of it, which is what caught the bugs unit tests could not.

**Tests:** 433, of which 12 skip themselves without a Postgres server.

**Known rough edges:**
- **There is no box.** Phase 5 is built and verified locally but no VPS or
  domain exists, so there is no public URL, `deploy.yml` has never run, and
  neither has a real ACME challenge. `caddy` itself is no longer in that
  bucket: Phase 9 exercised the shipped Caddyfile on a laptop against Caddy's
  own CA — a verified TLS 1.3 handshake, the four security headers, the
  `http://` → `https://` redirect, and `X-Real-IP` arriving such that
  Flask-Limiter counts the client and not the proxy. What is left is an account
  and a domain, not code.
- `IDEA.md` is one line, not yet the paragraph it asks for — the placeholder
  comment is still above it. Only the author can finish it.
- Profesia.sk scraping depends on Playwright + a real Chromium install, the
  heaviest dependency in the stack, and it is still the adapter most likely to
  break. It can no longer break *silently* — Phase 8 made every adapter report
  what the board showed it before filtering, and a source that showed nothing at
  all is an ERROR on the scan row — but that alarm has never fired against live
  markup, only against fixtures. One scheduled scan on the box settles it.
- **The digest has never met a real mail relay.** It has been run end to end
  against a socket on localhost, so the code path is proven; deliverability
  (SPF, DKIM, spam folders) needs the box, like TLS.
- ~~Rate-limit storage is in-memory and per-process, and the image ships two
  gunicorn workers.~~ **Fixed 2026-09-25 (Phase 10 item 1).** The image now runs
  one process with `--threads 8`, so the in-memory limiter is one bucket in one
  heap. Re-measured on the same four-container stack through Caddy: 30
  CSRF-valid POSTs against `/login`'s 10/min, first 429 at **#11**, 10 through —
  and the old `--workers 2` command, re-run on that same stack to prove the
  measurement measures something, still let **20** through with the first 429
  landing at #15 rather than #11, which is the non-determinism the bullet was
  really about. `RATELIMIT_STORAGE_URI` stays for the day a second process is
  genuinely wanted, and `check_runtime_config` now refuses `WEB_CONCURRENCY > 1`
  against `memory://` at boot so the combination cannot return.

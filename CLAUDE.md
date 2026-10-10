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
- **The title is a component, because the other four cannot tell what the job *is*.** `role`
  reads `jobs.title` and is the one component known for every scored job — every posting has a
  title. It is graded, not binary: a technology the user has (1.0) outranks the discipline they
  searched for (0.7) outranks a bare engineering word (0.35), because a search term is written
  for recall on a board and makes a poor precision signal alone. **Level words are stripped
  first** (`config.ROLE_LEVEL_WORDS`) — "junior" is the seniority component's word, and counting
  it twice is what put a *junior ESG consultant* at 100 on a frontend developer's list. A miss
  is a real `0.0`, not `None`: a title naming work you did not ask for is an answer, not missing
  data. Match role words at word boundaries with a small allowance for Slovak/Czech case endings
  ("webových"), never as substrings — `js` is a skill and lives inside `jsou`.
- **Eligibility is not a score, and `strict_match` is what makes it a cut.** A score ranks jobs
  you could take; `scoring.ineligible` answers a different question — whether you could take it
  at all — and three answers are non-answers rather than weak ones: the title names **another
  trade**, it names a **level above you**, or the job is **somewhere you cannot get to**. Weights
  could never have expressed this: 96 of 245 fresh Profesia postings — a receptionist, a
  toolmaker, a junior project manager — sat at *exactly* 37.6 on a frontend developer's list,
  above his threshold, because the four job-side components cannot tell what a job is. Each test
  refuses to fire on missing data, so a thin row is still ranked and never hidden. The reason is
  stored in the breakdown beside the components, so the inline panel a row's score toggles open
  can say which rule fired — and `display.INELIGIBLE` owns that sentence, because a 0 with the
  usual "average of what is
  known" caption is a lie about a job that was never averaged. Off by default: it throws jobs
  away, and that has to be asked for.
- **A level is read off the title, and a range keeps its lowest rung.** `jobs.seniority` stops at
  senior and is extracted from prose that says "lead a small team" and "a leading Slovak company"
  about jobs that are neither; a *title* states a level deliberately, and the rungs that matter
  most to a junior — lead, architect, head of — are ones that column has no word for. So
  `scoring.level_floor` reads `config.ROLE_LEVEL_ABOVE` against the title only, and takes the
  **minimum** of what it finds: "webový manažér (junior - senior)" invites a junior by name, and
  reading only the highest word would cut an ad addressed to them. The *score* reads the same
  ladder through `scoring.job_level` — title first, the extracted column only when the title is
  silent — and so does the `seniority_strict` gate, because one setting with two opinions zeroed
  the graduate advert the component had just scored 1.0. The **cut** keeps reading the title
  alone, and that asymmetry is the point: the column is good enough to rank a job with and not
  good enough to hide one. **One exception, and it is a narrow one:** `scoring.experience_floor`
  reads an explicit years-of-experience figure out of the description ("5+ years of experience",
  "minimálne 5 rokov praxe") and *is* allowed into the cut beside the title — a "Software
  Developer" naming no level at all, next to a body demanding five years, is the senior job in
  junior's clothing the cut exists to catch. It is not the same kind of evidence `jobs.seniority`
  is and is not read instead of that column's caution — a specific number is hard to state by
  accident the way the word "senior" turns up in "a leading Slovak company", so it earns
  title-grade trust on its own rather than reopening the column's.
- **An entry-level title earns its rung by naming the work, like every other title.** These
  are the engagements being hunted (`MISSION.md`) and they are what a title-only reading is
  worst at, so `scoring.entry_level` used to share the ladder's last rung with `ROLE_GENERIC`
  and carry any "študent" title past the field test. It saved the occasional untraded
  "Trainee programme" and admitted a flood: four of the first real list's eleven rows were
  student ads for a shop floor, an assembly line and a recruitment desk, and no vocabulary of
  other trades can catch a title that never says what the work is. The brief is coding jobs
  (`MISSION.md`, 2026-10-04), so the push-through is gone and the openings actually wanted
  lose nothing, because they name the trade: "Trainee frontend developer" is matched on its
  discipline two rungs higher. `entry_level` still owns the "entry level" tag on the row — it
  simply stopped deciding eligibility. Plain **"junior" was never one of its words**: it
  states a rung, which is the seniority component's question.
- **The place field outranks the prose about it, but no longer outright.** On a board that
  does not declare `worktype` (Profesia declares nothing), that column was read out of the
  description — so "možnosť práce z domu" in an ad for an office on Bottova 2a stores
  `remote`, and a perk is not a work permit. `scoring.reach` therefore asks the place field
  first. What it cannot do is tell that ad apart from a genuinely remote Bratislava job, so
  the answer has **three** values and not two: `REACH_OK`, `REACH_CLAIMED` (another town in
  your country, but the ad claims remote — half a location, ranked under certain work, never
  cut) and `REACH_NO`, which is the only one `ineligible` cuts. One derivation with two
  readers, which is also the bug it fixed: the cut consulted the place field and the
  component did not, so the same Bratislava job `ineligible` wanted to throw away was
  scoring a *perfect* 1.0 on its location. Every test refuses to fire on missing data —
  with no answer to "where are you", a town in a posting is evidence about nobody.
  `config.SK_CITIES` is that town list, districts included, because a Profesia place field
  carries a street address.
- **A neighbouring technology is not a miss.** `config.SKILL_ADJACENCY` groups the stacks
  where knowing one is most of knowing the other, which `MISSION.md` asks for by name — and
  without it an Angular advert read as *generic* to a React developer, the same 0.35 as a
  maintenance engineer, because the word is in no discipline's vocabulary and in nobody's CV.
  Groups rather than a graph, unioned by `scoring.adjacent_skills` because a technology can
  sit in two (kotlin is beside java and beside swift), expanded once per user in
  `db.get_user_prefs` beside `reachable`. Two readers: the role ladder gains a rung
  (`ROLE_ADJACENT`, under his own stack and over his discipline) and the skills component
  counts an adjacent requirement as `SKILL_ADJACENT_CREDIT` of one he has — half, because
  scoring the two the same would let a job asking for nothing he knows tie one asking for
  his CV. And **naming both ends names the middle**: `user_disciplines` infers `fullstack`
  from frontend + backend, without which "senior full stack developer" scored the generic
  rung on the list of a developer whose own terms said both.
- **The role ladder's fourth rung is other people's professions.** `ROLE_GENERIC` holds
  "engineer" and "inžinier" because on a job board they usually mean something — and in Slovakia
  they are mostly a factory. `config.ROLE_OTHER_FIELDS` is tested **after** the skill and
  discipline rungs and before the generic one, which is exactly what makes a broad list safe:
  "frontend developer for a logistics platform" is matched on its discipline and never reaches
  the vocabulary. Single words shared with software are spelled as phrases — "process engineer",
  never "process", and no bare "quality", because quality assurance is QA. For the same reason
  bare "front" is **not** one of the frontend discipline's words: on a title it finds "front
  office", and the user who types it still reaches the discipline by prefix.
- **A list with no board asked for shows the boards the instance uses — the admin's.**
  `enabled_sources` is one of `db.SCAN_SETTING_KEYS`: the crawl is shared and so is the board
  list it honours. Switching the crawl to Profesia alone left 8 000 rows from six disabled boards
  in "To review", a backlog no scan will ever refresh. Reading the *viewer's* copy instead is the
  trap — a second account keeps the seven defaults it never chose, and a pool scraped from a
  board outside that set goes invisible to everyone but the admin.
- **Skills coverage has a floor under its denominator** (`config.MIN_SKILL_EVIDENCE`). Extraction
  finds one skill in ~12% of described jobs and none in ~41%, so plain `overlap/len(job_skills)`
  most often scored a single word a perfect 1.0 — 77 jobs tied at 100 in the live pool. Thin
  evidence still ranks; it just cannot top the list on its own. Above the floor it is unchanged.
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
- **`ctx.seen()` counts listings the parser could *read*, never containers it found.** It is the
  silent-board alarm's only evidence, and a count taken off the card container is a number that
  cannot go wrong — so the alarm cannot fire. Kariéra counted `div.offer` and, measured against
  the live board, four realistic redesigns (the title heading renamed, its `h2` changed, the
  offer URL reshaped, the id dropped from it) each left six cards standing while the parser
  produced nothing. Count after the title, the link and the id have been extracted, as all three
  HTML adapters now do. **Pagination asks a different number** — the rows the board served,
  promoted slots included — because a full page this parser only partly understands is still a
  full page, and stopping on it truncates the crawl.
- **Migrations are additive and idempotent** (`backfill.py`) — never touch a user's statuses/scores.
  `init_schema` can add a column but not change a CHECK constraint; anything that alters one
  needs a table rebuild in `backfill.py` (see `migrate_scan_queue`) and a check at boot.
- **Scanning lives in the worker, and `scans` is the queue.** No scan state in module globals:
  a status poll must be answerable by a process that is not scanning. Triggering is admin-only
  and the crawl is global — one scrape serves every user, or the boards ban us.
  The crawl's terms, boards and window are the **admin's** settings — and `admin_user_id` is
  "the lowest-id admin", so **which** admin is a question the `users` table can answer wrongly:
  the pre-Phase-3 `local@jobmatch.local` row has no password hash, cannot be signed in as, and
  owned the live crawl for seven weeks while the real owner's board list was read by nothing.
  An account nobody can log into cannot own the instance (`backfill.demote_ghost_admin`), and
  never the last admin, because an unowned instance stops scanning. *Where* is the one thing
  that is not the admin's, because their answer is not the other accounts'. `db.crawl_regions` is the
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
- **A message carries its own `Date` and `Message-ID`, and leaves 7-bit clean.** Neither
  `EmailMessage` nor `smtplib` writes either header, and most relays quietly add them — which
  is why sending without them survived Phase 8 unnoticed, and why it is not a thing to rely
  on: `Date` is mandatory in RFC 5322 and a missing `Message-ID` is on Gmail's own list for
  bulk senders. The bodies are `quoted-printable` for the same reason in reverse: the default
  `8bit` put raw UTF-8 on the wire under an envelope that never said `BODY=8BITMIME`
  (`smtplib` only adds it for a non-ASCII *address*), and on these boards half the titles
  carry an á. The envelope sender is `MAIL_FROM` and so is `From:` — that alignment is what
  DMARC asks about after SPF passes — and the EHLO name is that domain too, never the
  container's dotless hostname, which `smtplib` turns into a bare `[172.18.0.4]`.

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
  so the number you filter on and the number you read cannot drift, and age is `jobs.posted_at`
  against `sources.base.posted_cutoff` — the *crawl's* own window function, so "7 days or newer"
  in the Jobs filter selects exactly what a `scan_days = 7` scan was allowed to fetch instead of
  meaning the same word a day differently. A filter value the server does not recognise is
  ignored rather than obeyed, so a hand-edited query string cannot empty the list.
- **A posting's age is derived from a stored date, never stored as an age.** `jobs.posted_at` is
  the absolute date a board's freshness string resolved to at scrape time (`dates.parse_posted`,
  which is why it takes a reference date); every age above it — `dates.days_ago`,
  `display.relative_date`, the Posted filter — subtracts from **today**, per request. That is
  the whole reason one stored row is right on every later day: a posting the board called
  "pred 4 dňami" on 3 Oct is stored as 29 Sep and reads *8 days ago* on 7 Oct. Storing the
  board's words, or a day count, would have pinned every row to the scan that found it and made
  a cumulative pool read as though it were all scraped this morning. The raw `freshness` text is
  kept for `backfill.py` to re-parse and is deliberately never shown. Two corollaries: an age is
  printed **in days for a month** (`display.DAYS_AGO_LIMIT`) because on a job board the digit is
  the fact — "last week" was what 8 days used to read as, and it threw that digit away — and a
  row whose date would not parse is `NULL`, so it is out of every freshness window rather than
  claiming the day of the scan. The sorts coalesce to `scraped_at` and the *filter must not*:
  when we saw a posting is not when it went up, and a three-year-old ad found this morning would
  otherwise top a freshness filter.
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

- **The web tier is one process, and the rate limits are why.** `RATELIMIT_STORAGE_URI`
  defaults to `memory://`, which is one bucket *per process* — the image shipped `--workers 2`
  and `/login`'s `10 per minute` let 20 through, non-deterministically, since which worker
  answered decided whether a request counted. Phase 4's "several workers are safe" was an
  argument about *scan state* (it lives in the `scans` row) and said nothing about limiter
  buckets. So: concurrency is `--threads` inside one process — the count chosen against
  SQLAlchemy's `pool_size=5 + max_overflow=10`, not the CPU count, because every request
  holds exactly one `g.db` connection for its life — and the process count lives in
  `WEB_CONCURRENCY` rather than in a `CMD` flag, precisely so `check_runtime_config` can
  **refuse** it above 1 against an in-memory store. Threads make module-level mutable state a
  live question: `db._ENGINES` is locked (two engines means two pools), `auth._DUMMY_HASH`
  races harmlessly on purpose, and `app._deployed` / `obs._configured` are boot-path only.
- **"All the others" is the list's own filter, and it can only ever move `new` rows.**
  `POST /api/jobs/decline-rest` is the end of a triage pass — mark what you applied to, say no to
  the rest in one click — and it answers the query string through the **same** `_job_filters()`
  the list and its count go through, so it cannot sweep a row the page was not showing, and it
  sweeps the ones past "Load more" because a pile is not the first 50 of itself. Both batch
  routes go through `_move_jobs`, whose `only_from` is the safety: a sweep moves rows out of
  `new` and an undo out of `declined`, so neither can touch a job that has since been marked by
  hand, and a second click of either changes nothing. The ids come back in the response and
  `POST /api/jobs/restore` takes them — the receipt is the client's, which is why undoing a bulk
  action needs no table to remember it in. Chunked at `_ID_CHUNK` because sqlite caps a statement
  at 999 bound variables and a pile is routinely larger than that.
- **Multi-user as of Phase 3**: argon2id + Flask-Login sessions, CSRF on every mutating route,
  rate limits on the credential endpoints. Every route is behind `@login_required` and every
  query is scoped by `current_user_id()` — adding a route means doing both. The two deliberate
  exceptions are `/` (the landing page, which branches on `current_user.is_authenticated`) and
  `/healthz`; both are public on purpose and neither reads a user's data. The job pool in
  `jobs` is the one thing that is deliberately shared.
- **A config file that is read by nobody is a config file that lies.** `config.py` catches
  python-dotenv's ImportError so a missing convenience dependency cannot break startup — but
  "not fatal" is not "silent": with the package absent from the interpreter that actually ran
  this instance, a fully populated `.env` configured *nothing*, and the app served for weeks on
  the dev `SECRET_KEY` while the file set a real one. `config.DOTENV_IGNORED` is checked
  **first** in `check_runtime_config`, ahead of the SECRET_KEY and debug refusals, because those
  read the very values that are not arriving. Refused on a deployment, warned about on a laptop,
  and logged by the worker too — it is the process `.env` configures most.
- **It expects to be deployed.** `SECRET_KEY` must come from the environment; startup refuses
  the dev key or debug mode on anything but a loopback bind, and `wsgi.py` calls
  `app.mark_deployed()` because gunicorn binds with `--bind` and never reads `HOST`.
  Put it behind the bundled Caddy for TLS — see `DEPLOY.md`.
- **The demo account is a real account with three holes punched in it**: no CV upload, no
  self-deletion, and never an admin (which is what stops it triggering a scan — the *schedule*
  has to honour that too, so `due_for_scan` asks `db.has_admin`, not "is there a user": a
  demo-enabled box's first account is the demo, and asking the second question crawled the
  boards on its settings ten seconds into the first boot). It is identified by email against
  `config.DEMO_EMAIL`, so `users` needs no column for it, and it is deliberately *not*
  read-only — the nightly reset is what makes that safe.
- Scrapers keep **polite delays** (5–16s between page requests on Slovak boards); don't remove them.
  API boards are fast; the default incremental scan window (last 7 days) keeps runs quick.
  **Fast is not the same as free, and one board says so in its own payload:** Remotive's
  `0-legal-notice` asks for "max. 4 times a day … excessive requests will be blocked", so its
  whole feed is read **once per scan** and the terms filter in Python — asking per term made 19
  requests a scan, 76 a day, for the same 18 jobs each time. A board that answers every query
  with its entire feed (confirmed twice live: `search`, `category`, `limit` and the bare URL all
  return the same ids, and `total-job-count` agrees) can only be read once; Remote OK was always
  this shape, Remotive became it.
- The DB is the source of truth and git-ignored — back it up if the tracker history matters.
- Don't commit to `main` — branch first. Commit/push only when asked.

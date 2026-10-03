# Changelog — jobmatch

One line per change, newest first. The `/roadmap-task` skill appends a sentence here after
each completed roadmap task. The plan lives in `ROADMAP.md`; the rationale in `PROJECT.md`.

## 2026-10-03
- **The list was full of jobs Oliver cannot take, and a score could not say so.** Of 245 fresh
  Profesia postings, 96 — a receptionist, a toolmaker, a junior project manager, an insurance
  intern — sat at exactly 37.6 on a frontend developer's list, above his threshold, because the
  four job-side components cannot tell what a job *is*; 38 more named a level above him and 93
  were in towns he cannot commute to. `scoring.ineligible` answers that as a separate question
  from the score — wrong trade, level above you, out of reach — and `strict_match` turns it from
  a note into a cut. Three findings underneath it: a *title* states a level where the extracted
  column cannot ("lead a small team" is prose about a job that is not), and a range keeps its
  lowest rung, so "webový manažér (junior - senior)" survives; Profesia declares no `worktype`,
  so "možnosť práce z domu" in an ad for an office on Bottova 2a had been storing `remote` and
  collecting a full location score, and the place field now outranks the prose; and "engineer" in
  Slovakia is mostly a factory, so `ROLE_OTHER_FIELDS` sits between the discipline rung and the
  generic one — after it, which is what lets "frontend developer for a logistics platform" keep
  its discipline. Bare "front" left the frontend vocabulary with it: on a title it finds "front
  office". The Jobs page was stripped to the list those rules make possible — eight filters, the
  score slider and the chip row all gone, the title now opening the posting on the board — and
  a list with no board asked for shows the admin's enabled boards rather than every board the
  instance has ever scraped. 245 → 17 fresh, 233 in the whole Profesia pool. 579 tests.

## 2026-10-01
- **The shared crawl was owned by an account nobody could log into** — `users` still held the
  pre-Phase-3 `local@jobmatch.local` row with an empty password hash and `is_admin = 1`, and
  `db.admin_user_id` is "the lowest-id admin", so every scheduled scan since 11 August read its
  boards, terms and window off a persona that cannot be signed in as. Phase 3 had already stopped
  *creating* that account precisely because it "would silently take the first-user-is-the-admin
  slot", and nothing ever went back for the row already in the table. `backfill.demote_ghost_admin`
  demotes a passwordless admin whenever a real one exists — never the last one, since an unowned
  instance stops scanning — and demotes rather than deletes, because those `user_jobs` rows are the
  single-user era's triage history. Applied to the live DB: the crawl now runs on
  `[redacted-email]`'s settings, whose board list was carried over from the ghost's so the
  shared pool did not narrow from seven boards to one.

- **A `.env` that cannot be read is now loud** — `config.py` catches python-dotenv's ImportError so
  a missing convenience dependency cannot break startup, which was right, but it was also silent:
  on the interpreter actually running this instance the package was absent, so a fully populated
  `.env` configured *nothing*. The app served for weeks on the built-in dev `SECRET_KEY` while the
  file set a real one, the worker crawled on the default 6-hour interval while the file said 0, and
  every edit to it changed nothing at all. `config.DOTENV_IGNORED` is set when the file exists and
  the loader does not, and it is checked **first** in `check_runtime_config` — before the
  SECRET_KEY and debug refusals, which cannot be trusted when the file feeding them is unread: a
  deployment is refused, a laptop gets a warning. The worker logs it too, being the process `.env`
  configures most and the one that runs for days unattended.

## 2026-09-28
- **The Jobs list can be asked how old a posting is** — a Posted filter (`1 / 3 / 7 / 14 / 30
  days or newer`) over `jobs.posted_at`, bounded by `sources.base.posted_cutoff` so the window in
  the dropdown and the `scan_days` window in Settings cannot mean the same word a day apart; the
  257 rows whose date no board gave are out of every window rather than assumed fresh, and the
  filter reads `posted_at` rather than the sorts' `COALESCE(..., scraped_at)` because a
  three-year-old ad found this morning is not a fresh job.

- **An age past a week keeps its digit** — `display.relative_date` now prints "8 days ago" for a
  month instead of collapsing 7–13 days to "last week", since on a job board the number of days
  *is* the fact being asked for. Pinned the whole derivation down while it was open: a posting is
  stored as an absolute date and every age is subtracted from today per request, so one stored row
  reads "4 days ago" on the day it was scraped and "8 days ago" four days later — now a test
  rather than a property nothing checked, plus a `CLAUDE.md` invariant.

- **Bounded the enrich phase, which is why no scan had finished since 10 September** — it reads
  every row in the pool still missing a description, which is right (a failed fetch is only ever
  repaired by a later scan retrying it) but was unbounded and ordered by `id`: 4 478 rows pending
  at 8–16 s each is about fifteen hours, and it spent them oldest-first, so scans 16–19 each died
  having enriched nothing anybody was going to read. Now newest-first under a
  `MAX_DETAIL_FETCHES` ceiling, with the remainder left to the next scan — the same "is the last
  one older than the interval?" schedule everything else runs on — and the progress strip showing
  what this run will attempt instead of how deep the queue is.

- **Set the crawl window to 7 days on the account that owns it** — the shared crawl reads
  `db.admin_user_id`'s settings, which is the legacy `local@jobmatch.local` (user 1), and its
  scan window was `0` = "look all the way back"; scans 16, 17 and 18 all died part-way through
  multi-hour runs because of it.

## 2026-09-25
- **Fixed the login rate limit by making the web tier one process** — `Dockerfile` now runs
  `--threads 8` and passes no `--workers`, so gunicorn takes the count from `WEB_CONCURRENCY`
  where `check_runtime_config` can refuse it above 1 against the in-memory limiter, and a lock
  around `db._ENGINES` settles what threads made a live question; re-measured on the
  four-container stack through Caddy, 30 POSTs to `/login` now 429 at the 11th instead of the
  21st, while the old `--workers 2` command re-run beside it still let 20 through.

- **Planned Phase 10, because Phase 9 ran out of halves an agent can do rather than running out
  of items** — its remaining seven are all hard-blocked on the box and the subdomain, so the new
  phase carries the four things still worth doing without one: the login rate limit the shipped
  image actually breaks (`--workers 2` against a per-process `memory://` store let 20 of 30 POSTs
  through a 10/min limit, to be fixed with one threaded process rather than a redis), the crawl's
  peak memory against the worker's own 1500m limit, a checker so a document cannot assert a count
  the tree contradicts (`PROJECT.md` went stale again in eleven days), and the robots.txt-first
  sourcing half of the EU-remote reach leak; the `## Later` bucket is emptied in the same pass —
  two bullets promoted, and the `IDEA.md` one deleted as false since `6ed3dfe`.

## 2026-09-23
- **Confirmed Remotive answers its whole feed to every query and cut the crawl from 19 requests
  a scan to 1** — the follow-up Phase 9 item 8 parked for a second live confirmation: `search`,
  `category`, `limit` and the bare URL all return the same eighteen ids (`total-job-count` says
  18 too), so the feed is read once and the terms filter in Python as they always have for
  Remote OK, which also brings us onto the max-4-requests-a-day the board asks for in its own
  `0-legal-notice` and stops the alarm being told 342 listings for a board showing 18.
- **Put the digest on a real socket for the first time, and found it was leaving without a
  `Date`, without a `Message-ID`, 8-bit under an envelope that never declared it, and willing
  to hand its password to an unencrypted relay** — the half of Phase 9 item 9 that needs no
  box: `tests/test_mail.py` now drives `mail.send` against a real SMTP server (STARTTLS, 465,
  AUTH, DATA) and asserts against the bytes that arrive, so both RFC-required headers plus
  `Auto-Submitted` are written here rather than hoped for from the relay, both bodies are
  quoted-printable (zero bytes over 127 on the wire, Slovak accents decoding back intact),
  credentials are refused on an unencrypted socket unless `SMTP_ALLOW_INSECURE_AUTH` says
  otherwise, and EHLO gives `MAIL_FROM`'s domain instead of the container's dotless hostname
  that smtplib turns into a bare `[172.18.0.4]`.

## 2026-09-22
- **Proved the silent-board alarm's counts against the boards' live markup, and found one board
  it could never have woken on** — the half of Phase 9 item 8 that needs no box: every enabled
  adapter was driven against the real boards and each `ctx.seen()` report cross-checked against
  the response rather than a fixture (all seven exact, including Kariéra's against the board's
  own "Aktuálna ponuka práce (6)" and Jobs.cz's 749 cards over 26 pages), which showed that
  Kariéra counted the card *container* instead of the offers it could read, so breaking the live
  page four realistic ways — the title heading renamed, its `h2` changed, the offer URL reshaped,
  the id dropped — left `seen` at six while the parser produced nothing; it now counts what it
  read, as Profesia and Jobs.cz already did, while pagination keeps asking the rows the board
  served so a promoted slot cannot truncate the crawl.

## 2026-09-17
- **A first boot crawled the job boards on the demo account's settings, and no longer does** —
  the half of Phase 9 item 5 that needs no box: a real four-container boot from a `.env` copied
  out of `.env.example` queued a scheduled scan ten seconds after `up`, before the admin
  `setpassword` creates existed, because `due_for_scan` asked `admin_user_id` — which falls back
  to the first account, and on a demo-enabled box the first account is the demo the worker itself
  had just created — so it now asks `db.has_admin`, which exists for exactly that distinction;
  the same boot proved `mark_deployed()` is what puts `Secure` on the session cookie (the
  container reported `SESSION_COOKIE_SECURE = False` and the cookie carried it anyway, and
  commenting the call out of `wsgi.py` dropped it), that a blank `SECRET_KEY` and the
  `JOBMATCH_DEBUG=1` the example ships each make `up --wait` exit 1 rather than serve, and that
  `.env.example` was missing one variable the code reads (`LOCAL_USER_EMAIL`), all guarded now by
  `tests/test_firstboot.py`.
- **The deploy's own checking could not fail, and now can** — the half of Phase 9 item 6 that
  needs no box: `docker compose up --wait` reports a service with no healthcheck `Healthy`
  while it crash-loops (measured: exit 1, eight restarts, `--wait` exited 0), which meant a
  deliberately broken `worker` — the only container that scrapes, digests and resets the demo —
  deployed green, so `worker` and `caddy` now declare one too; and the smoke test asserted a
  status code alone, so a parked page on the same hostname passed, which is fixed by finally
  wiring the `RELEASE` that `config.py` and `.env.example` both claimed the workflow passed and
  it never did, and reading the sha back out of `/healthz`; both shell bodies were driven
  against a real sshd and a real TLS endpoint until every failure exited non-zero, and
  `tests/test_deploy.py` guards it.

## 2026-09-13
- **Re-planned Phase 9 item 7's backups onto a free target and landed its box-free half** —
  the remote is an object store because Oracle reclaims idle *compute* and a backup VM is idle
  by definition, so `backup.sh` gained a `REMOTE_TOOL` (`rclone` alongside the unchanged
  `rsync`), remote pruning it never had, and a `backup-pull.sh` to fetch a dump back, without
  which the restore the roadmap asks for could only ever have used the local copy; verified by
  driving the whole script against a local rclone backend, where the pulled dump restored to
  the same `jobs`/`user_jobs`/`sum(match_score)` as live, and `rclone --immutable` turned out
  to replace an existing backup and exit 0 rather than refuse it.
- **Proved the image actually builds and runs on `linux/arm64`** — the half of Phase 9 item 4
  that needs no box — with a native `--no-cache` build on this aarch64 machine (every compiled
  dependency a prebuilt aarch64 wheel, no source builds) and Chromium 151 launching and
  rendering inside the worker's own 1500m/512m-shm limits; along the way the item's claim that
  "nothing has ever built this Dockerfile on arm64" turned out to be wrong by a week, and CI's
  arm64 Chromium check turned out to be a no-op that **exits 0 having run nothing** because
  `docker run` was missing `-i`, so the heredoc never reached `python3 -`.

## 2026-09-12
- **CI now builds the image on `linux/arm64` too**, the one half of Phase 9 item 4 that
  needs no box — as a matrix over platform rather than the two-platform build the roadmap
  asked for, because `load: true` is single-platform only and that literal would have gone
  green while silently dropping the `docker run` check that proves the image runs; the arm64
  leg also asserts Chromium's ELF `e_machine` against its own platform, since the base image
  ships browsers per architecture.
- **Re-planned Phase 9 item 4 onto a free box**, which means an ARM one — an Oracle Always
  Free Ampere A1 (2 OCPU / 12 GB since June, not the 4/24 everyone quotes) and a Public
  Suffix List subdomain so Let's Encrypt still issues, with the architecture risk measured
  rather than deferred: the Playwright base image's arm64 variant carries an **AArch64**
  Chromium at the exact revision 1.62.0 pins, every compiled dependency has an aarch64 wheel,
  and the two things that actually bite are Oracle reclaiming an idle instance and CI never
  having built this Dockerfile on arm64 at all.
- **The scorer now reads the job title**, through a fifth `role` component and a floor under
  the skills denominator — built off-roadmap on 09-10 and left unrecorded, now verified
  read-only against the live 7 970-job pool, where it clears out a top-of-list that was
  83 jobs tied at a perfect 100 ("junior esg consultant", one extracted skill, scored 100.0)
  and replaces it with React and Python roles, and mutation-tested, which found three
  invariants `CLAUDE.md` states but nothing tested — a role miss returning `None` instead of
  `0.0` let that same consultancy tie with "junior react developer" at 100 and passed the
  whole suite.

## 2026-09-06
- **Brought `PROJECT.md` back in line with the tree** — six adapters became seven, 318 tests 433, 2375 jobs 6842, and the key decision **"No FX conversion for salary"**, reversed a week ago, was replaced by the one that actually holds; the remote-work bullet still described a single `jobs.country`, and the rate-limit rough edge is a live defect rather than a hypothetical because the image ships two gunicorn workers.
- **Exercised `caddy` locally against the shipped Caddyfile** and found its body cap was dead
  config — a 25 MB POST was being rejected by Flask *after* crossing the proxy, so a
  Content-Length matcher now rejects it at the edge with nothing reaching `web`, and
  `{$CADDY_GLOBAL_OPTIONS}` lets a laptop or a staging ACME run without editing the file.

## 2026-09-02
- **Phase 7 and Phase 8 are now in the repository** — 71 files committed as `019359d` and
  merged to `main`, which until today held none of the landing page, demo, digest, places,
  jobs.cz adapter or FX conversion that `deploy.yml` would have shipped without them; all
  four CI jobs green, and `phase6-ui`/`origin/saas` retired so one branch means one thing.

## 2026-08-29
- **Planned Phase 9 — the launch**, the only unfinished work left in the roadmap: it found
  that Phases 7 and 8 are not in the repository at all (62 uncommitted files against a
  `main` that `deploy.yml` would deploy), that it is six repository secrets and not four,
  and that `caddy` can be exercised locally after all — ready for review, not started.
- **Two salaries are now compared on one period *and* one currency**: `salary.hourly_eur()`
  and its SQL mirror `HOURLY_EUR_SQL` convert to euros an hour for the pay filter and the
  "Best pay" sort, over an approximate, dated rate table that nothing stored reads — the live
  pool's entire top five was Czech before it, on the strength of koruna's extra digits.
- **A seventh board: jobs.cz, the Czech market.** `jobmatch/sources/jobscz.py` + a registry
  entry, on by default, defaulting to CZ in `places` — and the Czech relative and year-less
  absolute date forms went into `dates.py` next to the Slovak ones rather than into the
  adapter.
- **Only three of its date windows are real.** `24h`, `3d` and `7d` cut a 282-result search
  to 23/74/139; `1d`, `2d`, `4d`, `14d`, `30d`, `1m`, `1w` and a nonsense `99z` all returned
  the full 282 character for character, so the adapter only ever sends a token it watched
  move the count.
- **An ad's expiry sits in the same element as its posting date**, and reading "Končí za 3
  dny" as a birthday would date a job by its own death.
- **One link, two boards — and three ads in ten were unreadable.** Every card links to
  `www.jobs.cz/rpd/<id>/`, which redirects either to jobs.cz's server-rendered ad view or to
  an employer microsite that fetches its body client-side; measured over 30 live ads, 21 vs
  9. `fetch_detail` now tries plain HTTP first and renders only what that misses, so those
  nine stop landing unscored and re-fetched by every later scan forever.
- **The widget's 11-character skeleton is not the ad.** It mounts its container empty and
  fills it a moment later, so waiting on the element alone returned 11 characters against
  real bodies of 2 800–6 000 — which would have stored as a successful read of a job that
  then scores on nothing and is never retried.
- **The microsites come in two templates**, hanging the ad on different ids — worth three of
  thirty ads on the first full live scan. The adapter reads the class both templates build
  on, measured identical to whichever id applies across six unrelated employers, rather than
  collecting ids one scan at a time.
- **The enrich phase was erasing what boards had already told us.** "A source's structured
  fields beat regex extraction" was true everywhere except there, which overwrote
  `worktype`/`seniority`/`employment_type` from the description unconditionally — invisible
  until now because `jobscz` is the first board with both a `provides` declaration and a
  detail page. The first live scan erased a `hybrid` printed on the board's own card;
  `_enrich_phase` now skips the columns a source declares.
- **`nofluffjobs` and `startup.jobs` were refused, not skipped.** The first renders nothing
  without JavaScript and disallows `/api/` and `/posting/` under every language prefix;
  the second answers 403 to everything but robots.txt, its feed included. Both verified live
  and recorded in ROADMAP.md rather than half-built.

## 2026-08-28
- **A posting hiring in five places is now stored as five.** `places.country` was
  first-match-wins over a single free-text field, so Remotive's "LATAM, Europe, USA, Canada,
  APAC" was stored `US` and "Americas, Europe, Israel" was stored `IL` — both then
  unreachable for a European, though both say Europe out loud. `jobs.countries` holds every
  code the text names, packed as `|EU|US|CA|`, and reach is now a question about that set:
  the scorer intersects it, and the Jobs filter selects on it through the same expansion.
  On the live pool that is **19 jobs a European could not previously see**, out of 85 rows
  that name more than one place.
- **The chip still says one thing, and says how many it stands for.** `jobs.country` is now
  the *printed* half of one derivation rather than a second opinion: the specific place when
  everything the posting names sits inside one region ("Berlin, Germany — Europe" is a German
  job), the widest when it does not — so the card reads "Europe +4" and names the other four
  on hover, worded server-side like every other label it shows.
- **The new column is optional to read.** `places.COUNTRIES_SQL` and `places.stored_codes`
  fall back to the single code, so the window between `init_schema` adding `countries` and
  `backfill` filling it is not a window where every remote job scores unknown.
  `backfill.migrate_countries` packs existing rows — the one backfill that rewrites a column,
  because two columns out of step is the bug and not a migration of it — and
  `jobmatch.reextract` now replays placement over all rows next to the extraction it already
  replayed. Rehearsed end to end on a copy of the real 2 375-row database, which predates
  `jobs.country` entirely.
- **"northern america" matched nothing**, which is how Remotive spells it — a table gap the
  set made visible rather than hid.
- **The crawl asks the boards for a place, instead of scraping a planet and throwing most of
  it away.** Adapters now receive `ctx.regions` — where the people this instance crawls for
  can work — and narrow their request with it if their board takes a geography.
- **Where is the one crawl setting that is not the admin's.** Terms, boards and the scan
  window come from the admin because the pool is shared; for the same reason *where* cannot,
  since their answer is not the other accounts'. It is the union of every account's reach,
  read through the same `db.user_regions` the scorer uses — and **one user nobody can place
  empties it**, back to asking for everything, because a narrowed crawl would never fetch
  into the shared pool the job they were owed.
- **Jobicy is the one board of six that can be asked.** `&geo=<slug>` is real: verified live
  before it was relied on, an unknown slug is a 400, and a region still returns the postings
  addressed to the whole world — narrowed, `python` came back with the Mexico-only roles gone
  and every worldwide one kept. `places.covering_region()` picks the one region that covers
  everybody, and the rule is **one geo or none**: the board rate-limits (429 after fifteen
  quick requests), so narrowing may never cost a second pass — a crawl spanning two regions
  asks for everything rather than crawling the board twice.
- **The other three feeds send no geography, and that is now written down with its reason.**
  Remotive and Arbeitnow accept unknown query parameters and answer as if they were absent —
  `&geo=europe` on Remotive returns character-for-character the same jobs — so a narrowing
  guessed at rather than confirmed would have looked like it worked and quietly done nothing.
  Remote OK takes no parameters at all, not even the search term.

## 2026-08-27
- **Remote is no longer automatically a location match.** `_location_component` returned 1.0
  for every `worktype == "remote"` job whatever country it was in, so a US-only role scored
  full marks on location for a user in Bratislava and ranked exactly level with the EU roles
  it should have been beaten by — on the dashboard, in the Jobs list and in the digest. It is
  now judged against `jobs.country`, a column that already existed, and the fix reaches
  everything without scraping anything new.
- **A new setting, "where you can work"** (`user_regions`) — country/region codes, and a
  different question from `user_location`: one is a work permit, the other a commute, which
  is why a remote job in Denver is wrong for the second reason and not the first. On-site and
  hybrid still match the town; only remote reads the new setting.
- **It answers itself when you don't.** An empty setting is derived from the user's town —
  their country plus whatever region contains it, so the default is Canada + North America
  for a Canadian rather than Europe for everybody. Settings shows the derived answer as the
  live chips and says where it came from, and saving the profile without touching them keeps
  it derived, so moving to Vienna later still moves the answer.
- **One expansion, three readers.** `places.reachable_codes()` expands "where I can work"
  both ways — a region covers the countries inside it, a country is covered by a posting
  addressed to its whole region, and a worldwide posting reaches everybody — and the scorer,
  the Jobs country filter (`Somewhere I can work`, one entry instead of thirty) and, through
  the score, the digest all read it. A user who has answered nothing expands to nothing,
  which the filter ignores rather than obeys: an empty `IN ()` would have emptied the page.
- A row no board text could place stays **unknown** rather than unreachable — hatched, never
  a zero, per the scoring invariant. Stored scores refresh on the next scan or the next
  Settings save; no migration touches them.

## 2026-08-25
- The tracker and the Jobs list, reworked around the three questions they are actually
  opened with: *where did this application get to*, *how much does it pay*, and *where is it*.
- **The tracker's counts are now its filter.** Six slabs across the top — everything,
  waiting to hear, interviews, offers, rejected, withdrawn — and clicking one filters the
  table under it. A tally you cannot click is a number you then go and find by hand, which
  was the old page's whole problem. The tab lives in the URL (`/tracker#offer`), so it
  survives a reload and can be bookmarked, and moving a row's status re-files it under the
  tab it now belongs to.
- **"Waiting to hear" is two stored statuses in one tab**, because `applied` and
  `no_response` are the same wait and nobody filters on the difference. The grouping is
  server-side, in `display.APPLICATION_GROUPS`, next to the labels — the tabs, their counts
  and the dropdown in each row cannot drift apart on what a group contains, and a test
  asserts every status belongs to exactly one tab (a status in none would be an application
  that vanished from the page).
- **Pay, work mode and country get a row of their own on every job card**, above the grey
  tag soup they used to be buried in. The pay chip prints the board's range and the derived
  hourly rate together, and a posting that quotes nothing says **"No pay listed"** — absence
  is information, an empty gap is a bug the reader has to rule out.
- **`jobs.country`, a new derived column, and `jobmatch/places.py` to fill it.** Boards write
  location free-hand ("bratislava", "praha (hlavní město praha)", "usa only", "emea"); this
  turns that plus the board it came from into one code. Order is specific → general, and the
  board is a fallback rather than a first answer: an unrecognised town on profesia.sk is
  Slovakia, but "praha" on profesia.sk is still Czechia. A job nothing places stays unplaced
  and shows the board's own text.
- **Three new filters and a sort, all selecting on columns rather than on prose** — work
  mode, country, and pay (salary listed, or an hourly floor). The floor uses the same
  conversion the card prints, generated from one table in `salary.py`, so the number you
  filter on and the number you read cannot disagree; ranges are compared at their top
  ("could this job pay me 20 an hour?"). A filter value the server does not recognise is
  ignored rather than obeyed, so a hand-edited query string cannot silently empty the list.
- **Two bugs found by driving the pages in a browser rather than by reading them**: a second
  filter changed quickly could land its response *after* the first and put stale rows on
  screen (fixed with a request token), and a `#hash` pasted while already on the tracker
  moved nothing, because a same-document navigation never re-runs the page.
- `python3 -m jobmatch.backfill` fills `country` for rows that predate the column, and
  re-running it picks up anything a later addition to `places.py` can now place.
- 23 new tests (287 total). The screenshots were regenerated: the synthetic pool now leaves
  a third of its postings without a salary, which is roughly the real ratio and the case the
  Jobs page has to look right in.

## 2026-08-24
- Phase 8, the email digest. One new column (`user_jobs.digested_at`), two new modules, no
  new dependency — `smtplib` is in the standard library — and no new route.
- **The other half of a scanner nobody is watching.** A scan finds a 92% match at 04:00 and
  until now the only way to learn that was to open the page. The worker now mails each user
  their new matches, best score first, at most one message every `DIGEST_INTERVAL_HOURS`.
- **What goes in one is not a second opinion.** The digest selects on exactly the clause the
  dashboard counts "matched" with — `status = 'new'` and `match_score >= min_match_score` —
  plus the one thing an email adds: it has not been sent yet. The mail and the Jobs page
  cannot disagree about what counts, because there is one derivation.
- **A job is emailed once, and that is stored, not derived.** `digested_at` records what left
  the building. It has to be a fact about the *send*: a posting that crosses the threshold
  only because the user moved a weight is genuinely news to them, and no comparison against
  `scraped_at` would ever notice it. Jobs that did not fit in the message stay unmarked and
  lead the next one, so a first digest on a 783-match backlog is a top-10, not a data dump.
- **A broken relay costs latency, not matches.** The run is stamped *before* the send, so a
  mail server that is refusing connections is retried tomorrow rather than every ten seconds
  for as long as it stays broken; the jobs are marked only once the message is away, so
  nothing is lost by a failure. One user's bounce cannot stop the others getting theirs.
- **Scheduling is a query, not a timer** — the third feature to be built that way, after the
  scan schedule and the demo reset. "Is this user's last digest older than the interval?"
  survives a restart, cannot drift, cannot double-fire.
- **Off unless the instance can actually send mail.** No `SMTP_HOST` (or no `MAIL_FROM`, which
  every relay rejects a message without) means the worker skips the pass and Settings says so
  — the same shape as `SENTRY_DSN`. Mail is never a startup dependency. Each account has its
  own switch under Notifications, and the demo account is excluded outright: its address is
  published on the landing page, is nobody's inbox, and its nightly reset would hand it the
  same matches every day.
- **`jobmatch/mail.py` is the only module that opens a socket to a mail server** and knows
  nothing about jobs; `digest.py` builds a subject and two bodies and knows nothing about
  ports. The plain-text part is written first and is not an afterthought — it is what a
  terminal client, a screen reader and every spam filter reads.
- `python3 -m jobmatch.digest` with `--status` (who is due and what is waiting), `--dry-run`
  (build the mail, print it, send and mark nothing), and `--user … --force`.
- 34 new tests (264 total), plus a checkpoint run against a copy of the live 2375-job
  database through a real SMTP conversation on a socket.

## 2026-08-24
- Phase 8, the first two items: boards that cannot break quietly any more, and the whole
  loop tested end to end. No new dependency, no schema change, no new route.
- **A scraper that parses nothing now says so.** It was the one failure mode this app had
  that raised nothing and finished green: an adapter whose selectors stopped matching returns
  no jobs, which is exactly what an incremental scan with nothing new to find also returns.
  Adapters now report what the board *showed* them before any filtering, and a source is
  accused of returning "no listings at all" only when that number is zero — logged at ERROR
  so Sentry makes an event of it, and put on the scan row so the dashboard names the board.
  The scan still finishes `done`: a silent board is a warning about the board, not a failed
  crawl. A cancelled scan accuses nobody — we stopped it, it did not fail.
- **Profesia, the heaviest adapter, hardened.** A timed-out page is retried and then
  *reported* instead of ending that search term indistinguishably from "no results";
  pagination is capped rather than trusting the site's own end-of-results signal; the first
  page is fetched once instead of twice (the old loop went to the search URL and then
  straight back to it as page 1, with no politeness delay in between); and a row whose title
  link moved counts as unread, not as a listing, so half a redesign still trips the alarm.
- **Two things that fell out of it.** The enrich phase counts an empty description as a
  failed read — only the *raising* half was ever counted, so a detail selector that quietly
  stopped matching reported zero failures — and the four feed boards declare
  `has_detail_page = False`, which stops it asking them for a description their listing
  already carried and counting the empty answer against them.
- **The whole loop, end to end** (`tests/test_e2e.py`): signup → settings → queue a scan →
  the worker runs it → the jobs arrive extracted and scored → apply → the tracker → the
  pipeline. It keeps CSRF **on** and carries the token the way the pages do, and it runs the
  scan through `worker.run(once=True)` on the worker's own connection rather than reaching
  into `scan` from a request — the web tier only enqueues, and it asserts that too by
  checking the job table is still empty between the two. The fake board's two offers are
  written so the score is an assertion: 100 on all four components, and 0 on all four.
- 14 new tests (230 total).

## 2026-08-24
- Phase 7 (make it presentable — the CV surface), all of it. No schema change; one new
  dependency (`sentry-sdk`, inert without a DSN); three new routes.
- **`/` now greets a stranger.** A landing page with the pitch, the scoring formula, the
  architecture, and screenshots — rather than a login form, which is how a public instance
  reads as somebody's private tool. It is one route that branches on whether you are signed
  in, because `/` is the URL that gets shared and bookmarked.
- **A demo account anybody can click into**, and **it is not read-only** — the sliders move,
  jobs can be triaged, applications walk down the pipeline. A demo where nothing works is a
  screenshot. That is safe because the worker puts the account back every 24 hours, scheduled
  the same way scans are: a query ("is the last reset older than the interval?"), not a timer.
  Three things it may not do — upload a CV, delete itself, trigger a scan — and the last one
  falls out of it never being an admin rather than out of a special case.
- **Screenshots in both colour schemes**, shipped as `<picture>` with a `prefers-color-scheme`
  source on the landing page and in the README. The app has a dark mode; advertising it with
  light-only screenshots misrepresents it. `tools/screenshots.py` regenerates the lot from a
  `.backup()` copy of the live database, so they are one command rather than a chore that rots.
- **`/healthz`**, public and running a real `SELECT 1`, answering 503 when it fails. The
  failure it exists to catch is the web container up while Postgres is not — which the old
  compose healthcheck (`/login`) answers 200 to quite happily.
- **JSON logging**, one object per line, tagged with which container wrote it, with `extra={}`
  becoming queryable fields and request-scoped lines carrying `method`, `path` and `user_id`
  (never the email). Plus optional Sentry, which is off without a DSN and tolerates not being
  installed at all: a crash reporter must never be what stops the app booting.
- **README, CLAUDE.md and PROJECT.md rewritten.** The "don't expose this to the internet" note
  is gone, because it stopped being true three phases ago; what replaced it is what is actually
  true — it expects to be deployed, refuses its dev key off loopback, and wants the bundled
  Caddy in front. There is still no public URL, so the live link says so and says why.
- **Two bugs the checkpoint found.** The nav overflowed the viewport at 390 px — 554 px of
  links, so *every* page scrolled sideways, which Phase 6 missed because a full-page screenshot
  of a horizontally-scrolling page still looks fine. And "the first account is the admin" was
  implemented as "is the users table empty?", which a seeded demo account would have quietly
  broken; it now asks whether an admin exists, which is what the sentence always meant.
- Small one, but the kind that matters: `data/resumes/` was never added to `.gitignore` when
  Phase 2 moved CVs there from `data/cv.pdf`, so an uploaded CV was sitting untracked and
  perfectly committable. It is ignored now.
- Verified in a real browser at 390 px and from two cold starts (an empty database, and a
  populated pool with no accounts at all): one click seeds the demo and lands on a working
  dashboard in both. 216 tests (40 new, covering the demo's seeding, reset schedule and three
  refusals, the landing page's contract, `/healthz` and the log format).

## 2026-08-20
- Phase 6 (make the UI worth showing), all of it. Every page still black-and-white and
  vanilla JS; no new dependency, no schema change.
- **The scan overlay is gone.** A scan takes minutes by design — the Slovak boards are
  crawled with 5–16 s delays that are staying — so a full-screen modal was holding the page
  hostage over an operation nobody can hurry. It is now a progress strip under the nav,
  dismissible per scan (the scan's id goes in `sessionStorage`, so dismissing one does not
  hide the next), and triage continues underneath while it runs.
- **A job detail view**, the one item here that needed a route: `/jobs/<id>` plus
  `GET /api/jobs/<id>`. `jobs.description` was scraped, stored and never shown — reading a
  posting meant leaving the app. The list and the detail share one `_job_payload()`, so a job
  cannot word itself two ways; the description stays out of the list payload, where it would
  be 4 KB × 50 rows.
- **The score says how it is made up.** The four components were hidden in a `title=` tooltip
  no touch device ever sees. They are now four bars — a compact stack on every row, a labelled
  panel when you click the score — and **"not known" is hatched, never an empty bar**, because
  the whole point of scoring over *known* components is that missing data is not a penalty.
- **Real loading and error states**: skeleton rows in the shape of the list that is coming, a
  dimmed-but-still-there list while a filter change is in flight (the page no longer blanks
  every time a slider moves), a retry button on a failed load, and the three Settings save
  buttons report *beside themselves* instead of in a toast that is gone in 3.5 s.
- **Paging behind the truncation.** `/api/jobs` takes `limit`/`offset`, answers with `total`
  and `has_more`, and clamps `limit` to `JOB_LIMIT` so one caller cannot ask for the table.
  The client pages 50 at a time with "Load more"; the old `JOB_LIMIT = 500` cut-off that the
  UI apologised for in prose is gone.
- **Mobile**: the tracker's six-column table and the job grid both become cards under 720 px,
  with every tracker cell carrying its own label.
- **Dark mode**, as predicted, a token swap — with one correction: the chrome needed its own
  `--surface` tokens, because swapping `--ink` and `--paper` turns the black nav bar into a
  white slab at night, which is the one thing a dark mode must not do.
- **Accessibility and keyboard**: `aria-pressed` on the tabs and preset chips, an `aria-live`
  toast, a skip link, `:focus-visible` rings, and the power feature the layout was asking for
  — `j`/`k` between jobs, `a`/`d` to apply or decline, `s` for the breakdown, `/` to search.
- Small ones: the dashboard asks `/api/stats` once instead of twice, and there is a favicon.
- Verified in a browser against a copy of the live 2375-job database: all four pages plus the
  new one, in both colour schemes, at phone width, with the strip live over a running scan and
  a `d` keypress moving a job out of Matches and the next one into the cursor. 176 tests
  (12 new, covering the detail endpoint's tenant scoping and the paging contract).

## 2026-08-14
- Phase 5 (containerize and deploy), everything that does not need a VPS: a multi-stage
  `Dockerfile` on Microsoft's Playwright image running non-root as one image with two
  entrypoints, a `docker-compose.yml` of `web` / `worker` / `db` (Postgres 16) / `caddy`, a
  `DEPLOY.md` runbook, `deploy/backup.sh` + `deploy/restore-check.sh`, and a `deploy.yml`
  workflow that ships on green CI. **The box does not exist yet, so there is no public URL and
  the ship line is not crossed** — what is left is a Hetzner account, a domain and four
  repository secrets, not code.
- The Postgres dialect gaps are closed and *verified against a real server*, not reasoned
  about. The `datetime('now')` / `date('now')` schema defaults became constructs with one
  rendering per dialect, chosen to keep the timestamp **string shape** identical on both
  backends so `display.py` never learns which one it is reading; sorting had to spell out
  `NULLS LAST`, since SQLite and Postgres order NULLs oppositely by default.
- CI grew two jobs: `postgres` (the 12 parity tests, which skip themselves without
  `TEST_DATABASE_URL`, plus a `wsgi` import against Postgres) and `image`, which builds the
  Dockerfile — a broken image is now a red build instead of a broken deploy.
- **Verified by running it, not by reading it.** The real Flask app booted on Postgres 16 and
  every page and JSON route was walked; the same fixture scored 300.0 on both backends and the
  queue kept its guarantees (a second enqueue is a no-op, a second claim gets nothing). The
  containers came up healthy, gunicorn served `/login`, and `setpassword` worked inside the
  image. `backup.sh` then produced a dump that `restore-check.sh` restored into a scratch
  database, matching all seven tables and `sum(match_score) = 1290.7`.
- **The restore check was then made to fail, twice** — a check that cannot fail is not a check.
  A dump missing a `jobs` row exits 3 on the foreign-key violation; a dump silently missing one
  `application_events` row exits 1 and names that row. The live database was unchanged after
  every run and the scratch database was dropped even on the failures.
- **Closed the caveat every checkpoint since Phase 2 has carried:** the live database had 0
  applications, so the application/event half of migration and restore was covered by unit
  tests only. Three applications were walked down the real pipeline through the actual routes
  (applied → interview → offer → rejected), and those rows are now what the negative control
  detects the loss of. Covered by data instead of by assumption.

## 2026-08-13
- Phase 4 (scanning out of the web process): `scans` is now the queue. A trigger inserts a
  `queued` row and returns; `python3 -m jobmatch.worker` claims it with a conditional
  `UPDATE … WHERE status = 'queued'` and writes progress, a heartbeat and the cancel flag back
  to the row. No scan state in module globals any more, so any gunicorn worker can answer a
  status poll — and `wsgi.py` is no longer single-worker-only.
- The worker also schedules the shared crawl (`SCAN_INTERVAL_HOURS`, default 6) and reconciles
  scans a dead worker left `running`. **Scheduling is a query, not a timer** — "is the newest
  scan older than the interval?" survives a restart, cannot drift and cannot double-fire, so
  there is no APScheduler dependency after all.
- Orphan reconciliation moved out of `app.bootstrap_db()`: a restarting web process says
  nothing about whether a scan is running, while a missing heartbeat says exactly that. A row
  silent for `SCAN_STALE_SECONDS` (90) is failed, which is also what stops it blocking the queue.
- Manual scans are admin-only (403 otherwise), and so is cancelling; the dashboard button and
  the overlay's cancel are rendered only for an admin, and a scheduled scan no longer throws a
  full-screen modal at a reader who never asked for one. Everyone can still watch a scan.
- `python3 app.py` runs the worker loop in a thread (`SCAN_IN_PROCESS`), so local development
  stays one command; `wsgi.py` deliberately does not, since N web processes would mean N crawlers.
- **A live database could not be queued into.** `scans` predates the `queued` status, and
  `init_schema` can add a column but not change a CHECK constraint — every enqueue failed with
  an IntegrityError. `backfill.migrate_scan_queue` rebuilds the table (create/copy/drop/rename,
  as in Phase 2), and both entrypoints now say so loudly at boot instead of letting the first
  person to press Scan find out. Found by running against a copy of the live DB, not by a test.
- Timestamps written by the queue come from Python rather than `datetime('now')`, which is one
  fewer SQLite-ism for the Phase 5 Postgres switch to fix.
- 34 new tests (152 total). Verified against a copy of the live 2375-job DB: the rebuild kept
  all 14 scan rows and the score sum of 37011.5, a real remoteok scan ran queued → claimed →
  done with its phases visible from a *second* connection, `kill -9` mid-scan was reconciled on
  restart with nothing lost or duplicated, and SIGTERM ended a running scan as `cancelled`.

## 2026-08-12
- Phase 3 (auth and security): Flask-Login sessions over argon2id hashes, with signup, login,
  logout and a `/login` redirect in front of every page and a 401 JSON body in front of every
  API route. `current_user_id()` now returns the logged-in user instead of resolving to the
  implicit local one, and `app.bootstrap_db()` no longer creates that user — an account
  arrives through signup or `jobmatch.setpassword`, and the first one created owns the
  instance as admin.
- Signup is open but env-gated by `ALLOW_SIGNUP` (default on), alongside `SESSION_DAYS`,
  `MIN_PASSWORD_LENGTH`, `SESSION_COOKIE_SECURE` and the two `RATELIMIT_*` variables. Session
  cookies are HttpOnly + SameSite=Lax, and get `Secure` automatically on a non-loopback bind.
- Added `python3 -m jobmatch.setpassword` — sets a password on an existing account or creates
  the first admin, reading the password from a prompt or `JOBMATCH_PASSWORD` rather than argv.
  This is what makes the migrated `local@jobmatch.local` account, which owns all 2375 live
  jobs, loginable: it was created with an empty `password_hash` that no argon2 verify can
  satisfy.
- CSRF (Flask-WTF) on every mutating route; `app.js` sends the token from a `<meta>` tag on
  each fetch, and a 401 now navigates to the login page instead of toasting on a dead page.
  Rate limits (Flask-Limiter) on login, signup, account deletion and scan triggering.
- CV uploads are checked for the `%PDF-` header before `save()`, so a renamed non-PDF never
  reaches the disk. Account deletion added: it verifies the password, then erases the CV file
  along with the user's `user_jobs`, settings, applications and events, leaving only the
  shared job pool.
- Login answers "no such account" and "wrong password" with one identical message, and spends
  an argon2 verify on an unknown address so response timing does not enumerate accounts.
  `?next=` only follows a same-site path.
- **`sqlalchemy` was missing from `requirements.txt`** since Phase 2 — a fresh install or CI
  run had no reason to have it. Added, along with the four auth dependencies.
- 59 new tests (118 total), including the Phase 3 checkpoint as two test clients. Verified
  against a copy of the live DB: `setpassword` made the migrated account usable with its 52
  declined / 2323 new and score sum 37011.5 intact, and a second user saving weights rescored
  only their own 2375 rows.

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

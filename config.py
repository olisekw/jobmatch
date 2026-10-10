# JobMatch configuration
# Code-level constants + deployment settings read from the environment.
# Runtime settings (scoring weights, match threshold, search terms, user
# preferences) live in the `settings` table and are edited from the web UI.
#
# Every environment variable below is documented in `.env.example`; the
# defaults are the local-dev ones, so `python3 app.py` needs no env at all.

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

# A local `.env` is a convenience, not a requirement: real deployments inject
# the environment directly, so a missing python-dotenv must not break startup.
# But "not fatal" is not the same as "silent", and the difference cost a week of
# this instance's life: with python-dotenv absent from the interpreter actually
# running `app.py`, a fully populated `.env` was read by nobody — the app served
# on the built-in dev SECRET_KEY and the worker crawled on the default interval,
# while the file on disk said otherwise and every edit to it changed nothing.
# So the file's existence is the thing that makes its loss worth reporting:
# `DOTENV_IGNORED` is checked by `app.check_runtime_config`, which refuses to
# boot a deployment that way and warns loudly on a laptop.
DOTENV_PATH = BASE_DIR / ".env"
DOTENV_IGNORED = False
try:
    from dotenv import load_dotenv

    load_dotenv(DOTENV_PATH)
except ImportError:  # pragma: no cover - depends on what is installed
    DOTENV_IGNORED = DOTENV_PATH.exists()

# One wording, because both entrypoints report it and they must not describe the
# same silence two ways: the web tier refuses to boot a deployment on it, the
# worker logs it.
DOTENV_IGNORED_MESSAGE = (
    f"{DOTENV_PATH} exists but python-dotenv is not installed, so nothing in it "
    "is being read — SECRET_KEY, the scan interval and the SMTP settings are all "
    "at their built-in defaults. Run: pip install -r requirements.txt"
)


def _env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


# ── Paths ────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("DATA_DIR") or BASE_DIR / "data")
RESUME_DIR = DATA_DIR / "resumes"
# Pre-multi-tenancy CV location; `jobmatch.backfill` moves it into RESUME_DIR.
LEGACY_RESUME_PDF = DATA_DIR / "cv.pdf"


def resume_path(user_id):
    """Where one user's CV lives. Personal data — one file per user, never shared."""
    return RESUME_DIR / f"{int(user_id)}.pdf"


# Owner of the data on a single-user install: created by the CSV migration and
# by `jobmatch.backfill`, and the account `jobmatch.setpassword` gives a real
# password to. The web app no longer creates it — a user arrives via signup.
LOCAL_USER_EMAIL = (os.environ.get("LOCAL_USER_EMAIL") or "local@jobmatch.local").lower()

# ── Database ─────────────────────────────────────────────────
# SQLAlchemy-style URL so Phase 5 can point at Postgres without a rewrite.
# `sqlite:///rel/path.db` is relative, `sqlite:////abs/path.db` absolute —
# the same convention SQLAlchemy uses.
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'jobmatch.db'}"

SQLITE_URL_PREFIX = "sqlite:///"


def sqlite_path(url=None):
    """Filesystem path behind a sqlite:// URL, or None for any other driver."""
    url = DATABASE_URL if url is None else url
    if not url.startswith(SQLITE_URL_PREFIX):
        return None
    return Path(url[len(SQLITE_URL_PREFIX):])


# Kept as a module constant because `db.get_conn()` and the tests read it
# directly; it is None once DATABASE_URL points at a non-sqlite backend.
DB_PATH = sqlite_path()

# ── Deployment ───────────────────────────────────────────────
# Signs the session cookie. The default is fine locally and refused in
# production — see `app.check_runtime_config()`.
DEV_SECRET_KEY = "dev-insecure-do-not-use-in-production"
SECRET_KEY = os.environ.get("SECRET_KEY") or DEV_SECRET_KEY

DEBUG = _env_bool("JOBMATCH_DEBUG", False)
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = _env_int("PORT", 8000)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# `text` for a human reading a terminal, `json` for one object per line. The
# default is the local one on purpose: a deployment says so in its compose file
# (which is also where `JOBMATCH_COMPONENT` labels web vs worker), and deriving
# it from the bind would make the two entrypoints disagree — gunicorn never
# reads HOST. Consumed by `jobmatch/obs.py`.
LOG_FORMAT = os.environ.get("LOG_FORMAT", "text").strip().lower()

# What is running. The deploy workflow passes the commit sha; /healthz reports
# it and every Sentry event carries it, so a report can be tied to code.
RELEASE = os.environ.get("RELEASE") or "dev"

# Unset is the normal case and turns error reporting off completely. Nothing
# about monitoring may be a startup dependency — see `obs.init_sentry`.
SENTRY_DSN = (os.environ.get("SENTRY_DSN") or "").strip()
SENTRY_ENVIRONMENT = os.environ.get("SENTRY_ENVIRONMENT") or "production"
# 0 = errors only, which is what fits a free-tier quota: tracing samples every
# request and spends the month's events in a day.
SENTRY_TRACES_SAMPLE_RATE = _env_float("SENTRY_TRACES_SAMPLE_RATE", 0.0)

# Serving on anything but loopback is a deployment. Several defaults below
# tighten themselves off this, so a deployed instance is safe without being
# told; `app.check_runtime_config()` refuses the dev key on the same test.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
IS_LOOPBACK = HOST in LOOPBACK_HOSTS

# ── Sessions and accounts ────────────────────────────────────
# `Secure` would make the cookie invisible over plain http, which is exactly
# what local dev serves — so it follows the bind rather than being hardcoded.
# HOST only describes `python3 app.py`: gunicorn binds with --bind and never
# reads it, so `app.mark_deployed()` turns this on for that case. Setting the
# variable explicitly wins over both, which is the escape hatch for running
# gunicorn locally over plain http.
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", not IS_LOOPBACK)
SECURE_COOKIE_WAS_SET = bool((os.environ.get("SESSION_COOKIE_SECURE") or "").strip())
# Days a login survives. Lax + this is the whole session policy.
SESSION_DAYS = _env_int("SESSION_DAYS", 14)

# Open signup is what the SaaS direction wants; the flag is what closes the
# door on a deployed instance without a code change.
ALLOW_SIGNUP = _env_bool("ALLOW_SIGNUP", True)

# Shortest password accepted at signup. Length is the only rule — composition
# rules push people towards "Password1!" and buy nothing.
MIN_PASSWORD_LENGTH = _env_int("MIN_PASSWORD_LENGTH", 10)

# Flask-Limiter backend. In-memory is per-process: correct for one web process,
# and silently wrong for two — each counts its own bucket, so `10 per minute`
# became 20 and *which* worker a request landed on decided whether it counted.
# Measured through Caddy: 30 POSTs to /login got 20 through before the first
# 429. The fix is one process (see WEB_CONCURRENCY below), not a shared store;
# this stays here for the day a second process is genuinely wanted.
RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI") or "memory://"
RATELIMIT_ENABLED = _env_bool("RATELIMIT_ENABLED", True)

# gunicorn's own name for the worker-process count: its `workers` setting
# defaults to `int(os.environ.get("WEB_CONCURRENCY", 1))` (confirmed against
# gunicorn 26.2.0 in the image). The Dockerfile therefore passes no `--workers`
# at all, so this variable is the only thing that sets it and a `CMD` string
# cannot disagree with the limiter. Read here purely so `check_runtime_config`
# can refuse the one combination that is wrong — >1 process against an
# in-memory limiter. Concurrency inside the one process is `--threads`, which
# the in-memory limiter is fine with because it is one bucket in one heap.
WEB_CONCURRENCY = _env_int("WEB_CONCURRENCY", 1)

# How many reverse proxies sit in front of the app — 1 for the Caddy in
# docker-compose.yml, 2 if a CDN is added later. Only consulted by
# `app.mark_deployed()`, i.e. under gunicorn: the dev server has no proxy, and
# trusting a hop that is not there lets a caller name their own IP in
# X-Forwarded-For and walk past the per-IP rate limits. 0 turns it off.
TRUSTED_PROXY_HOPS = _env_int("TRUSTED_PROXY_HOPS", 1)

# ── Scanning and the worker ──────────────────────────────────
# Scanning is a scraping operation: off means the trigger endpoint refuses
# rather than silently doing nothing, and the worker stops scheduling.
SCAN_ENABLED = _env_bool("SCAN_ENABLED", True)

# How often the worker enqueues a scan of its own. The crawl is shared by every
# user (see ROADMAP.md), so this is the only thing that decides how hard the
# boards get hit — 0 disables scheduling and leaves only manual scans.
SCAN_INTERVAL_HOURS = _env_int("SCAN_INTERVAL_HOURS", 6)

# How often the worker looks for a queued scan. A manual scan waits this long
# at worst before it starts, so keep it small; it is one indexed SELECT.
WORKER_POLL_SECONDS = _env_int("WORKER_POLL_SECONDS", 10)

# A running scan writes a heartbeat this often, and is declared dead — its row
# closed out so it stops blocking the queue — after this long without one.
# The gap has to be several heartbeats wide, or a slow write reaps a live scan.
SCAN_HEARTBEAT_SECONDS = _env_int("SCAN_HEARTBEAT_SECONDS", 15)
SCAN_STALE_SECONDS = _env_int("SCAN_STALE_SECONDS", 90)

# `python3 app.py` runs the worker loop in a thread so local development needs
# one command, not two. Deliberately ignored by wsgi.py: under gunicorn every
# worker process would start one, and N processes scraping the same boards is
# exactly what Phase 4 exists to prevent.
SCAN_IN_PROCESS = _env_bool("SCAN_IN_PROCESS", True)

# ── The public demo (Phase 7) ────────────────────────────────
# On means the landing page offers a seeded account anyone can sign into and
# actually use — see `jobmatch/demo.py` for why it is not read-only. Off means
# the account is neither created nor offered, which is the default because
# every instance except the public one is somebody's real job search.
DEMO_MODE = _env_bool("DEMO_MODE", False)

# The demo's credentials are published on the landing page on purpose: the
# password is not protecting anything, and a recruiter who wants to see the
# login form should be able to use it. Overridable so a fork's demo is not
# reachable with a password that is in this repository.
DEMO_EMAIL = (os.environ.get("DEMO_EMAIL") or "demo@jobmatch.app").strip().lower()
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD") or "demo-account-please"

# How often the worker puts the demo back. 0 turns the schedule off and leaves
# `python3 -m jobmatch.demo` as the only way to reset it.
DEMO_RESET_HOURS = _env_int("DEMO_RESET_HOURS", 24)

# ── Email digest (Phase 8) ───────────────────────────────────
# Unset SMTP_HOST is the normal case and turns digests off completely: the
# worker skips the pass, Settings says the instance cannot send mail, and
# nothing about a missing relay is a startup dependency — the same shape as
# SENTRY_DSN above.
SMTP_HOST = (os.environ.get("SMTP_HOST") or "").strip()
SMTP_PORT = _env_int("SMTP_PORT", 587)
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD") or ""
# 465 is implicit TLS (encrypted before a byte of SMTP), 587 is plaintext until
# STARTTLS upgrades it. Each default follows from the other, so naming the port
# is normally the only thing a relay needs told.
SMTP_SSL = _env_bool("SMTP_SSL", SMTP_PORT == 465)
SMTP_STARTTLS = _env_bool("SMTP_STARTTLS", not SMTP_SSL)
SMTP_TIMEOUT = _env_int("SMTP_TIMEOUT", 30)
# A password sent over an unencrypted socket is a password on the wire, and
# `jobmatch.mail` refuses to do it: with both SMTP_SSL and SMTP_STARTTLS off,
# AUTH would hand the relay credentials in the clear. The escape hatch exists
# for the one case where it is not a mistake — a relay on the box's own
# loopback — and has to be asked for by name.
SMTP_ALLOW_INSECURE_AUTH = _env_bool("SMTP_ALLOW_INSECURE_AUTH", False)

# Who the digest comes from. Defaults to the SMTP username because that is the
# address a relay will let us send as; a different From: usually needs the
# domain to be verified with the provider first.
MAIL_FROM = (os.environ.get("MAIL_FROM") or SMTP_USER).strip()
MAIL_FROM_NAME = os.environ.get("MAIL_FROM_NAME") or "JobMatch"
# Overrides the name this client gives at EHLO and the right-hand side of the
# Message-ID. Unset — the normal case — both come from the From: domain; see
# `jobmatch.mail.domain`, which derives it rather than freezing it here, so a
# MAIL_FROM changed after import cannot leave the two disagreeing.
MAIL_DOMAIN = (os.environ.get("MAIL_DOMAIN") or "").strip()

# Absolute base for the links in an email — `url_for` needs a request and a
# digest is built by the worker, which has none. Unset means the digest links
# each job straight to the board it came from instead of into the app.
PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")

# How often a user can get one. 0 turns the schedule off and leaves
# `python3 -m jobmatch.digest` as the only way to send one.
DIGEST_INTERVAL_HOURS = _env_int("DIGEST_INTERVAL_HOURS", 24)

# How many jobs one email carries. The rest are not marked as sent, so they
# lead the next digest rather than being lost — see `jobmatch/digest.py`.
DIGEST_MAX_JOBS = _env_int("DIGEST_MAX_JOBS", 10)

# ── Web scraping ─────────────────────────────────────────────
# How far back a scan is allowed to reach, in days, and the bounds the Crawl
# panel offers. It is one number with three readers — the boards' own freshness
# parameter, `sources.base.posted_cutoff`, and the Jobs page's Posted filter —
# so the bounds live here rather than as `min`/`max` attributes on an input the
# server never checked. There is **no "look all the way back"**: the window is
# what sizes the enrich backlog, and an unbounded one (`scan_days = 0`) left
# 4 478 rows waiting on a polite scraper — see MAX_DETAIL_FETCHES below. 30 is
# also the widest Posted window the Jobs filter offers (`app.POSTED_WINDOWS`),
# which is what keeps "30 days or newer" able to name the whole pool a scan
# could have fetched.
SCAN_DAYS_MIN = 1
SCAN_DAYS_MAX = 30


def scan_window(value):
    """A stored `scan_days` as a usable window: an int inside the bounds.

    Clamped rather than rejected, because this is the *read* side — the scan
    runs off whatever the admin's row happens to hold, and a row written before
    the bounds existed (or by hand) must still produce a crawl. A legacy 0 meant
    "all the way back", so it reads as the widest window allowed, not as one day.
    """
    try:
        days = int(value)
    except (TypeError, ValueError):
        return SCAN_DAYS_MAX
    if days <= 0:
        return SCAN_DAYS_MAX
    return max(SCAN_DAYS_MIN, min(SCAN_DAYS_MAX, days))


# Politeness delays between requests (seconds)
MIN_PAGE_DELAY = 5.5        # between search-result pages
MAX_PAGE_DELAY = 13.0
MIN_DETAIL_DELAY = 8.0      # between job-detail fetches
MAX_DETAIL_DELAY = 16.0

# How many descriptions one scan will fetch before leaving the rest to the next
# one. The enrich phase reads every row in the pool that still has no
# description, not just the ones this scan found — a fetch can fail, and a later
# scan retrying it is the only thing that ever fixes that. Unbounded, it is a
# queue that a crawl can fill faster than a polite scraper can drain: a window
# of `scan_days = 0` left 4 478 rows waiting, and at the delays above that is
# fifteen hours of fetching, which is why scans 16, 17 and 18 each died part-way
# through one. 300 is an hour at the average delay, against a 6-hourly schedule.
#
# The backlog is worked **newest first**, which is the half that matters more
# than the ceiling: whatever a scan does get through is then the rows somebody
# is about to read, and `CLAUDE.md`'s "shown unscored until the next scan"
# already says an un-enriched row is a state the app is built to survive.
MAX_DETAIL_FETCHES = _env_int("MAX_DETAIL_FETCHES", 300)

# Playwright timeouts (milliseconds)
TIMEOUT_GOTO = 45000
TIMEOUT_CARD = 25000
MAX_RETRIES = 2

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# ── Skill detection ──────────────────────────────────────────
# Case-insensitive regexes; word boundaries added at match time for short tokens.
CODING_PATTERNS = [
    # Frontend
    r'html[5]?', r'css[3]?', r'sass', r'scss', r'\bless\b',
    r'javascript', r'typescript', r'\bjs\b', r'es6', r'es2015',
    r'react native', r'react\.?js', r'react', r'next\.?js',
    r'vue\.?js', r'\bvue\b', r'nuxt\.?js',
    r'angular', r'angularjs',
    r'svelte', r'sveltekit',
    r'tailwindcss', r'tailwind', r'bootstrap', r'material ui', r'\bmui\b',
    # Backend
    r'python', r'\bc\b', r'c\+\+', r'c#', r'\bjava\b', r'ruby', r'\bphp\b', r'\bgo\b', r'rust',
    # Databases
    r'\bsql\b', r'mysql', r'ms sql', r'mssql', r'oracle', r'postgresql', r'postgres',
    r'mongodb', r'redis',
    # Frameworks
    r'node\.?js', r'django', r'flask', r'spring', r'laravel', r'express',
    r'graphql', r'apollo', r'relay',
    # State management
    r'redux', r'react query', r'zustand', r'mobx',
    # Data science
    r'numpy', r'pandas', r'scikit\-learn', r'tensorflow', r'keras',
    r'sqlalchemy', r'beautifulsoup', r'requests',
    # DevOps & tools
    r'\bgit\b', r'github', r'gitlab', r'docker', r'kubernetes', r'ci/cd', r'jenkins',
    r'webpack', r'vite', r'parcel', r'gulp', r'grunt', r'\bnpm\b', r'yarn', r'pnpm',
    # Other
    r'mendix', r'power ?bi', r'business central', r'dynamics 365',
    r'flutter', r'firebase',
]

# ── Worktype / seniority / employment-type detection ─────────
# Ads decline "práca" freely ("ponúkame prácu z domu"), so the noun is matched as
# pr[áa]c\w* — the phrase after it is what carries the meaning.
WORKTYPE_PATTERNS = {
    "remote": [
        r'\b(pr[áa]c\w* z domu|home ?office|remote|fully remote|100% remote|pr[áa]c\w* na diaľku|remote work|work from home)\b',
        r'\b(full ?remote|pr[áa]c\w* výlučne z domu|možnosť pracovať z domu kdekoľvek)\b',
    ],
    "hybrid": [
        r'\b(hybrid|hybridný režim|hybridný model|kombinovaný režim|čiastočne v kancelárii|2[-–]?3? dni v office|3 dni home office)\b',
        r'\b(home ?office \+ office|niekoľko dní v kancelárii|hybridný pracovný model)\b',
        # Explicitly *partial* work-from-home. Without these, "50% práce z domu"
        # matches the plain remote pattern and the ad reads as fully remote — which
        # then also hands it a full location score. Bare "možnosť práce z domu" is
        # deliberately NOT here: fully-remote ads use that phrasing too.
        r'\b(\d{1,3} ?% ?(času )?pr[áa]c\w* z domu|čiastočne ?(pr[áa]c\w*)? z domu|občasn\w* pr[áa]c\w* z domu)\b',
        r'\b(kombináci\w* s? ?pr[áa]c\w* z domu|\d{1,2} ?(dni|dňa|deň|dní) (v týždni )?z domu)\b',
    ],
    "onsite": [
        r'\b(onsite|v kancelárii|plne v office|pr[áa]c\w* v kancelárii|na pracovisku|vyžaduje prítomnosť|pr[áa]c\w* na mieste|denná dochádzka)\b',
        r'\b(bez možnosti home office|žiadny home office|pr[áa]c\w* výlučne v office)\b',
    ],
}

SENIORITY_PATTERNS = {
    "junior": [
        r'\b(junior|začiatočník|začínajúci|entry level|absolvent|graduate|bez skúseností|študent|student)\b',
        r'\b0[-–]?[23] roky\b',
    ],
    "medior": [
        r'\b(medior|mid[- ]?level|stredne pokročilý)\b',
    ],
    "senior": [
        r'\b(senior|skúsený|lead developer|expert level)\b',
    ],
}

# A numeric years-of-experience requirement, read separately from the word-based
# `SENIORITY_PATTERNS` above: a specific number ("5+ years", "minimálne 5 rokov
# praxe") is a much higher-precision signal than a categorical word like
# "senior", which also matches prose with nothing to do with the role's level
# ("a leading Slovak company"). Each pattern must capture the number in group 1.
# Slovak/Czech forms spell their diacritics out, same as `SENIORITY_PATTERNS`:
# this text is only lower-cased before matching, never diacritic-stripped.
#
# Order matters: `extract.extract_experience_years` blanks out each pattern's
# matches before trying the next, so a range ("3-5 years") must be listed
# before the bare "N years ... experience" pattern below it — otherwise the
# bare one would also match the "5" inside "3-5" and the range's own lower
# bound would be lost to the higher number it was deliberately avoiding.
EXPERIENCE_YEARS_PATTERNS = [
    # "3-5 years of experience" — the lower bound is the stated minimum
    r'\b(\d+)\s*[-–]\s*\d+\s*years?\s*(?:of\s*)?experience\b',
    # "5+ years", "5+ years of experience", "5+ years' experience" — but not
    # a client or company's own tenure ("With 20+ years of proven success",
    # "clients have been with us for 7+ years"), which the live pool showed
    # using this exact bare "N+ years" shape just as often as a candidate
    # requirement does.
    r'\b(\d+)\+\s*years?\b(?!\s*(?:of\s+(?:proven\s+)?(?:success|history|innovation)'
    r'|,?\s*and\b))',
    # "minimum 5 years of experience", "at least 5 years experience" — the
    # qualifier alone is not enough: "at least 18 years old" is an age
    # requirement, not an experience one, so "experience" must follow.
    r'\b(?:minimum|min\.?|at least)\s*(\d+)\s*years?\s*(?:of\s*)?(?:relevant\s*)?experience\b',
    # Deliberately no bare "N years ... experience" pattern with no qualifier
    # at all: live postings use that exact shape to describe the *company's*
    # history ("Sisecam, who has 88 years of experience") at least as often as
    # a candidate requirement, and every genuine English requirement found in
    # the live pool carried an explicit "+", "minimum" or "at least" anchor.
    # "3-5 rokov praxe" — the lower bound
    r'\b(\d+)\s*[-–]\s*\d+\s*rok(?:y|ov|ů)?\s*(?:praxe|prax\w*|skúsenost\w*|zkušenost\w*)',
    # "zkušenosti alespoň 4 roky", "prax minimálne 5 rokov" — the noun first,
    # the qualifier and number after it
    r'\b(?:praxe|prax\w*|skúsenost\w*|zkušenost\w*)\s+'
    r'(?:minimálne|min\.?|aspoň|najmenej|minimálně|alespoň|nejméně)?\s*(\d+)\+?\s*rok',
    # "5+ rokov praxe", "min. 5 rokov praxe", "min. 4 roky zkušeností" — the
    # number first, the noun after it
    r'\b(?:minimálne|min\.?|aspoň|najmenej|minimálně|alespoň|nejméně)?\s*(\d+)\+?\s*rok(?:y|ov|ů)?\s*'
    r'(?:praxe|prax\w*|skúsenost\w*|zkušenost\w*)',
]

# The lowest years count that implies each level — highest threshold met wins.
# Below the lowest key, a years figure says nothing about level on its own
# (the existing junior "0-2 roky" shape is read by `SENIORITY_PATTERNS`, not
# this table).
EXPERIENCE_YEARS_LEVEL = {3: "medior", 5: "senior"}

EMPTYPE_PATTERNS = {
    # The Slovak noun is "úväzok" (with ä); boards that strip diacritics emit
    # "uvazok". Both spellings, and any case ending, are matched via [úu]v[äa]z\w*
    # — the qualifier in front ("plný" / "čiastočný") is what fixes the meaning,
    # so being permissive about the endings is safe.
    "fulltime": [
        r'\b(pln\w*|100%) ?[úu]v[äa]z\w*\b',
        r'\b(full ?time|full-time|fulltime)\b',
        r'\b(HPP|hlavný ?pracovný ?pomer)\b',
    ],
    "parttime": [
        r'\b(čiastočn\w*|ciastocn\w*|polovičn\w*|pol[čc]asov\w*|\d+[-–]hodinov\w*) ?[úu]v[äa]z\w*\b',
        r'\b(part ?time|part-time)\b',
        r'\b(brigáda|DPP|DPČ|Dohoda o pracovnej činnosti|Dohoda o vykonaní práce|študentská práca)\b',
    ],
    "internship": [
        r'\b(stáž|praxis|internship|absolventský program|trainee|odborná prax|študentská stáž)\b',
    ],
    "freelance": [
        r'\b(freelance|voľná noha|SZČO|živnosť|kontrakt|projektová spolupráca|self-employed)\b',
    ],
}

# ── Location / preference parsing (user inputs + resume) ─────
LOCATION_PATTERN = (
    r"(bratislava|košice|kosice|žilina|zilina|nitra|trnava|prešov|presov|"
    r"banská bystrica|banska bystrica|martin|poprad|trenčín|trencin)"
)

# ── Search-term presets (seed values for the Settings UI) ────
SEARCH_PROFILES = {
    "frontend": [
        "front", "developer", "programmer",
        "javascript", "react", "typescript",
        "frontend", "ui", "ux",
    ],
    "fullstack": [
        "fullstack", "full-stack", "full stack", "developer", "programmer",
        "javascript", "react", "node", "python",
        "backend", "frontend",
    ],
    "backend": [
        "backend", "developer", "programmer",
        "python", "node", "java", "go",
        "api", "server", "database",
    ],
    "native": [
        "native", "mobile", "developer", "programmer",
        "react native", "flutter", "swift", "kotlin",
    ],
    "devops": [
        "devops", "engineer", "developer",
        "docker", "kubernetes", "ci/cd", "infrastructure",
        "cloud", "aws",
    ],
    "custom": [
        "react", "front", "programator", "typescript",
        "native", "web", "developer",
        "software", "mobile", "student", "internship",
        "frontend", "backend", "python", "junior",
        "graduate", "javascript", "tester", "engineer",
    ],
}

DEFAULT_SEARCH_PROFILE = "custom"

# ── Role relevance (what the job title says the work is) ─────
#
# The scorer's fifth component reads the one field every posting has and every
# human reads first. It exists because the other four could not tell a React
# role from a "junior ESG consultant": a description that mentions Python once
# gives skills 1.0, and the title — the thing that says what the job *is* —
# was not read at all.
#
# Graded by how *specific* the match is, because a search term is tuned for
# recall on a board and makes a poor precision signal on its own. The user's
# own skills are the sharpest evidence, their discipline next, a bare dev-role
# word weakest — "engineer" appears in "network security engineer" too.
#
# DISCIPLINES maps a canonical discipline to the words a title writes it with,
# in the languages the Slovak and Czech boards use. A user's disciplines are
# whichever of these their search terms name, so this is a vocabulary the app
# knows, never a preference it holds — the preference stays in their settings.
ROLE_DISCIPLINES = {
    # Bare "front" is deliberately absent: on a title it finds "front office"
    # and "front desk", and it floated an SPP contact-centre operator onto a
    # frontend developer's list at 44. A user who *types* "front" still lands
    # here, because `user_disciplines` matches a term against these words by
    # prefix — the recall belongs on the search side, not on the title side.
    "frontend": ["frontend", "front-end", "front end", "ui", "ux",
                 "web", "webov"],
    "backend": ["backend", "back-end", "back end", "api", "server"],
    "fullstack": ["fullstack", "full-stack", "full stack"],
    "mobile": ["mobile", "mobilny", "android", "ios", "native"],
    "data": ["data", "datovy", "analytics", "machine learning", "ai"],
    "devops": ["devops", "sre", "infrastructure", "platform", "cloud"],
    "qa": ["qa", "tester", "testing", "quality assurance", "automation test"],
}

# A title that names one of these is at least *some* kind of engineering job,
# which is worth more than a title that names none — and less than one that
# names the discipline the user asked for. Diacritics are stripped before the
# match, so "vývojár" is listed the way it is written and found either way.
ROLE_GENERIC = [
    "developer", "vyvojar", "programator", "programmer", "coder",
    "engineer", "inzinier", "software", "architect", "it specialist",
]

# Professions that are not this one. "Engineer" and "inžinier" are in
# ROLE_GENERIC because they are usually worth something on a job board — but in
# Slovakia they are mostly a factory: a *logistics & packaging engineer*, a
# *maintenance engineer (robotics)* at Volvo and a *junior procesný inžinier
# výroby* each collected a generic hit and cleared a frontend developer's
# threshold. A title naming one of these names work this person does not do.
#
# Tested *after* the skill and discipline rungs on purpose, which is what makes
# a broad list safe: "frontend developer for a logistics platform" is matched
# on its discipline and never reaches this vocabulary. Multi-word terms are
# used wherever a single word is shared with software — "process engineer" and
# not "process", and no bare "quality", because quality assurance is QA.
ROLE_OTHER_FIELDS = [
    # Plant, production and maintenance
    "vyroby", "vyroba", "process engineer", "procesny inzinier", "maintenance",
    "udrzby", "udrzba", "nastrojar", "mechanical engineer", "strojny inzinier",
    "electrical engineer", "elektrotechnik", "body in white", "zvaranie",
    "quality & process",
    "technolog", "konstrukter", "operator vyroby",
    # Logistics and supply
    "logistics", "logistika", "packaging", "warehouse", "sklad", "supply chain",
    "zasobovanie", "spedicia",
    # Commercial, office and front desk
    "sales", "obchodny", "obchodnik", "account manager", "marketing",
    "recepcny", "receptionist", "kontaktneho centra", "contact centre",
    "call centre", "call center", "operator", "operatorka", "predavac",
    "accountant", "uctovnik", "payroll", "hr", "human resources", "recruiter",
    "personalist", "insurance", "poistovaci", "advokat", "pravnik",
    # Caught by the entry-level rung and not by anything above it. A title
    # saying "študent" earns a rung now (see `scoring._role_component`), so the
    # trades the brigade ads are actually for have to be named or they ride in
    # on the word: a Nike shop floor in Eurovea, a law firm's filing, a
    # recruitment team, a company assistant's desk. "predaj" and "pokladn"
    # cover the shop-counter spellings the way "sklad" already covers the
    # warehouse ones, and "pravn" the adjective that "pravnik" misses.
    "predaj", "pokladn", "pravn", "naborov", "asistent", "assistant",
    "finance analyst", "financny analytik",
    # Reached through ROLE_GENERIC's "engineer"/"inžinier" and nothing else, so
    # named here or they ride in on it: a *mechano inžinier* for building
    # services (TZB), a quality engineer, an IP network post. "kvality" is one
    # word on purpose — "inžinier/ka kvality" defeats a two-word phrase — and
    # it is safe where a bare "quality" would not be, because a QA title is
    # matched on the qa discipline two rungs earlier and never arrives here.
    # "network" stays a phrase for the same reason "process" does.
    "kvality", "mechano", "tzb", "network engineer", "network solution",
    # Care, trade and transport
    "zdravotn", "opatrovate", "kuchar", "vodic", "ridic", "skladnik",
    "stavbyvedu", "murar", "elektrikar",
]

# Level words are the seniority component's job. Counting them here too is what
# floated "junior ESG consultant" to the top of a frontend developer's list, so
# they are removed from a user's search terms before any of the above is asked.
ROLE_LEVEL_WORDS = {
    "junior", "medior", "senior", "student", "graduate", "absolvent",
    "internship", "intern", "staz", "trainee", "praxe", "prax", "entry",
    "lead", "principal", "head",
}

# Words that, in a *title*, say the job sits above the person reading it. Only
# ever matched against `jobs.title`, never the description: prose says "lead a
# small team" and "a leading Slovak company" about jobs that are neither, while
# a title states a level on purpose. Slovak spellings are listed as written and
# found with diacritics stripped, the way the role vocabulary above is.
ROLE_LEVEL_ABOVE = {
    "medior": ["medior", "mid-level", "mid level"],
    "senior": ["senior", "sr", "skuseny"],
    "lead": ["lead", "team lead", "tech lead", "vedouci", "veduci", "hlavny"],
    "principal": ["principal", "staff engineer", "expert"],
    "architect": ["architect", "architekt"],
    "head": ["head of", "manager", "manazer", "riaditel", "director"],
}

# A title naming a *range* keeps its lowest rung: "webový manažér (junior -
# senior)" is a real opening for a junior, and cutting it because the word
# senior appears would throw away an ad that invites them by name.

# Slovak towns, for the one question `worktype` cannot answer on a board that
# does not declare it. Profesia's work-mode column is read out of the ad's
# prose, so "možnosť práce z domu" in an ad for an office on Bottova 2a stores
# `remote` — a perk, not a work permit. When the place field names a town in
# the user's own country that is not their town, that is a commute they cannot
# make, and the place field is the deliberate one. Street addresses carry the
# town too ("ševčenkova 34, petržalka"), so city districts are listed.
SK_CITIES = [
    "bratislava", "petrzalka", "ruzinov", "nove mesto", "karlova ves",
    "kosice", "presov", "zilina", "nitra", "trnava", "banska bystrica",
    "trencin", "martin", "poprad", "prievidza", "zvolen", "povazska bystrica",
    "michalovce", "nove zamky", "spisska nova ves", "komarno", "levice",
    "humenne", "bardejov", "liptovsky mikulas", "piestany", "ruzomberok",
    "topolcany", "trebisov", "dubnica nad vahom", "vranov nad toplou",
    "senec", "dunajska streda", "malacky", "pezinok", "sala", "rimavska sobota",
]

# Technologies close enough that knowing one is most of knowing the other.
# `MISSION.md` asks for this by name — "if you're a React developer you can also
# switch to another stack, Angular say; a job in a neighbouring technology is
# not a miss" — and without it an Angular advert read as *generic* to a React
# developer, the same 0.35 as a maintenance engineer, because "angular" is not
# in any discipline's vocabulary and not in his CV.
#
# Groups, not a graph: within one of these, any member is adjacent to any other,
# which is coarse and is the right amount of structure for the question being
# asked ("could he pick this up?"). A technology may sit in two groups — kotlin
# is beside java and beside swift — so `scoring.adjacent_skills` unions the
# groups a skill appears in. Spelled the way a title spells them, with no bare
# "next" (it is an ordinary English word) and no bare "net".
SKILL_ADJACENCY = [
    ["react", "angular", "vue", "svelte", "preact", "nextjs", "next.js", "nuxt"],
    ["javascript", "js", "typescript", "ts"],
    ["python", "django", "flask", "fastapi"],
    ["node", "nodejs", "node.js", "express", "nestjs"],
    ["css", "sass", "scss", "less", "tailwind", "bootstrap"],
    ["sql", "postgres", "postgresql", "mysql", "mariadb", "sqlite"],
    ["docker", "kubernetes", "k8s", "podman"],
    ["java", "kotlin", "scala"],
    ["c#", "csharp", ".net", "dotnet"],
    ["php", "laravel", "symfony"],
    ["swift", "kotlin", "flutter", "react native"],
    ["git", "github", "gitlab", "bitbucket"],
]

# What a requirement he could pick up is worth against one he already has, in
# the skills component. Half: an adjacent stack is a real answer to "could you
# do this job" and a worse one than having done it, and scoring the two the
# same would let a job asking for nothing he knows tie one asking for his CV.
SKILL_ADJACENT_CREDIT = 0.5

# How much of the job's detected skill list counts as enough evidence to trust
# the coverage figure. A description that yielded one skill and matched it is
# *not* the same fit as one that yielded five and matched five, and scoring
# both 1.0 is what put 77 jobs at a perfect 100 with a single word between them.
MIN_SKILL_EVIDENCE = 3

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
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass


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


# ── Paths ────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("DATA_DIR") or BASE_DIR / "data")
RESUME_DIR = DATA_DIR / "resumes"
# Pre-multi-tenancy CV location; `jobmatch.backfill` moves it into RESUME_DIR.
LEGACY_RESUME_PDF = DATA_DIR / "cv.pdf"


def resume_path(user_id):
    """Where one user's CV lives. Personal data — one file per user, never shared."""
    return RESUME_DIR / f"{int(user_id)}.pdf"


# Owner of the data on a single-user install, created at startup when the
# users table is empty. Phase 3 replaces the implicit login with a real one.
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

# Scanning is a scraping operation: off means the trigger endpoint refuses
# rather than silently doing nothing. Phase 4 moves execution to a worker.
SCAN_ENABLED = _env_bool("SCAN_ENABLED", True)

# Read-only public demo (Phase 6). Declared here so deployment config has one home.
DEMO_MODE = _env_bool("DEMO_MODE", False)

# ── Web scraping ─────────────────────────────────────────────
# Politeness delays between requests (seconds)
MIN_PAGE_DELAY = 5.5        # between search-result pages
MAX_PAGE_DELAY = 13.0
MIN_DETAIL_DELAY = 8.0      # between job-detail fetches
MAX_DETAIL_DELAY = 16.0

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

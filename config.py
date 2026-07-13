# JobMatch configuration
# Code-level constants only. Runtime settings (scoring weights, match threshold,
# search terms, user preferences) live in the SQLite `settings` table and are
# edited from the web UI.

from pathlib import Path

# ── Paths ────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

DB_PATH = DATA_DIR / "jobmatch.db"
RESUME_PDF = DATA_DIR / "cv.pdf"

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
WORKTYPE_PATTERNS = {
    "remote": [
        r'\b(práca z domu|home ?office|remote|fully remote|100% remote|práca na diaľku|remote work|work from home)\b',
        r'\b(full ?remote|práca výlučne z domu|možnosť pracovať z domu kdekoľvek)\b',
    ],
    "hybrid": [
        r'\b(hybrid|hybridný režim|hybridný model|kombinovaný režim|čiastočne v kancelárii|2[-–]?3? dni v office|3 dni home office)\b',
        r'\b(home ?office \+ office|niekoľko dní v kancelárii|hybridný pracovný model)\b',
    ],
    "onsite": [
        r'\b(onsite|v kancelárii|plne v office|práca v kancelárii|na pracovisku|vyžaduje prítomnosť|práca na mieste|denná dochádzka)\b',
        r'\b(bez možnosti home office|žiadny home office|práca výlučne v office)\b',
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
    "fulltime": [
        r'\b(pln[ýy] ?úvaz(e|ek|ku|ok)|plny ?uvaz(e|ek|ku|ok))\b',
        r'\b(plný|plny) ?[úu]vaz(e|ek|ku|ok)\b',
        r'\b(full ?time|full-time|fulltime)\b',
        r'\b(100% ?[úu]vaz(e|ek|ok)|HPP|hlavný ?pracovný ?pomer)\b',
    ],
    "parttime": [
        r'\b(čiastočný ?úvaz(e|ek|ok)|ciastocny ?uvaz(e|ek|ok)|part ?time|part-time|polovičný ?úvazok|polcasový ?úvazok|\d+[-–]hodinový úväzok)\b',
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

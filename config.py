# JobMatch Configuration
# Central settings for scraping, matching, and feature extraction

from pathlib import Path

# Paths - customize INPUT_TXT if you want it elsewhere
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
SRC_DIR = BASE_DIR / "src"

INPUT_TXT = DATA_DIR / "inputs.txt"      # REQUIRED: Your job preferences
RESUME_PDF = DATA_DIR / "cv.pdf"         # REQUIRED: Your CV (PDF format)
RESUME_TXT = DATA_DIR / "resume.txt"
USER_CSV = DATA_DIR / "user.csv"
JOBS_CSV = DATA_DIR / "jobs.csv"
RESULTS_CSV = DATA_DIR / "results.csv"
APPLIED_CSV = DATA_DIR / "applied.csv"

# ── Web Scraping ─────────────────────────────────────────────
# Delays between requests (in seconds) - adjust to be respectful
MIN_DELAY = 8
MAX_DELAY = 16

# Playwright timeouts (milliseconds)
TIMEOUT_GOTO = 45000    # Page load timeout
TIMEOUT_CARD = 25000    # Card element wait timeout
MAX_RETRIES = 2         # Retry failed scrapes

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# ── Skill Detection ──────────────────────────────────────────
# Add more skills as needed - patterns are case-insensitive
CODING_PATTERNS = [
    # Frontend
    r'html[5]?', r'css[3]?', r'sass', r'scss', r'less',
    r'javascript', r'typescript', r'js', r'es6', r'es2015',
    r'react', r'react\.?js', r'next\.?js', r'react native',
    r'vue\.?js', r'vue', r'nuxt\.?js',
    r'angular', r'angularjs',
    r'svelte', r'sveltekit',
    r'tailwind', r'tailwindcss', r'bootstrap', r'material ui', r'mui',
    # Backend
    r'python', r'c', r'c\+\+', r'c#', r'java', r'ruby', r'php', r'go', r'rust',
    # Databases
    r'sql', r'mysql', r'ms sql', r'mssql', r'oracle', r'postgres', r'postgresql',
    r'mongodb', r'redis',
    # Frameworks
    r'node\.?js', r'django', r'flask', r'spring', r'laravel', r'express',
    r'graphql', r'apollo', r'relay',
    # State management
    r'redux', r'react query', r'zustand', r'mobx',
    # Data science
    r'numpy', r'pandas', r'scikit\-learn', r'tensorflow', r'keras',
    r'sqlalchemy', r'beautifulsoup', r'requests',
    # DevOps & Tools
    r'git', r'github', r'gitlab', r'docker', r'kubernetes', r'ci/cd', r'jenkins',
    r'webpack', r'vite', r'parcel', r'gulp', r'grunt', r'npm', r'yarn', r'pnpm',
    # Other
    r'mendix', r'power ?bi', r'business central', r'dynamics 365',
    r'flutter', r'firebase',
]

# ── Job Search Terms ────────────────────────────────────────
# Predefined search profiles - choose one or create custom list
SEARCH_PROFILES = {
    "frontend": [
        "front", "developer", "programmer",
        "javascript", "react", "typescript",
        "frontend", "ui", "ux"
    ],
    "fullstack": [
        "fullstack", "full-stack", "full stack", "developer", "programmer",
        "javascript", "react", "node", "python",
        "backend", "frontend"
    ],
    "backend": [
        "backend", "developer", "programmer",
        "python", "node", "java", "go",
        "api", "server", "database"
    ],
    "native": [
        "native", "mobile", "developer", "programmer",
        "react native", "flutter", "swift", "kotlin"
    ],
    "devops": [
        "devops", "engineer", "developer",
        "docker", "kubernetes", "ci/cd", "infrastructure",
        "cloud", "aws"
    ],
    "custom": ["react"]  # Add your own terms here
}

# Select which profile to use (options: "frontend", "fullstack", "backend", "native", "devops", "custom")
ACTIVE_SEARCH_PROFILE = "frontend"

# Or manually set search terms (overrides ACTIVE_SEARCH_PROFILE if not empty)
SEARCH_TERMS = SEARCH_PROFILES[ACTIVE_SEARCH_PROFILE]

# Example: Custom search terms (uncomment to use)
# SEARCH_TERMS = [
#     "developer", "programator", "inzinier", "vývojár", "programmer",
#     "software", "javascript", "react", "front", "fullstack", "student"
# ]

# ── Location Detection ───────────────────────────────────────
LOCATION_PATTERN = (
    r"(bratislava|ba|košice|kosice|ke|košický|"
    r"žilina|nitra|trnava|prešov|banská bystrica)"
)

# ── Seniority Levels ─────────────────────────────────────────
SENIORITY_PATTERN = (
    r"(junior|medior|senior|"
    r"začiatočník|začínajúci|stredne pokročilý|skúsený|"
    r"absolvent|entry level|mid level|begin)"
)

# ── Work Type Detection ──────────────────────────────────────
WORKTYPE_PATTERN = (
    r"(remote|fully remote|100% remote|"
    r"práca z domu|home ?office|work from home|"
    r"hybrid|hybridný|kombinovaný režim|"
    r"onsite|v kancelárii|office|na pracovisku)"
)

# ── Job Compatibility Matching ──────────────────────────────
# Scoring weights for job matching (0-1 scale)
SKILL_MATCH_WEIGHT = 0.4      # How important skill match is
WORKTYPE_MATCH_WEIGHT = 0.25  # Remote/hybrid/onsite preference
LOCATION_MATCH_WEIGHT = 0.2   # Location preference
SENIORITY_MATCH_WEIGHT = 0.15 # Experience level match

# Minimum match score to consider a job (0-100)
MIN_MATCH_SCORE = 30

# ── CSV Columns ──────────────────────────────────────────────
USER_COLUMNS = ["Location", "Skills", "Seniority", "Worktype"]

JOB_COLUMNS = [
    "Title", "Company", "Link", "Description",
    "Skills", "Worktype", "Seniority", "EmploymentType",
    "Salary", "Location", "Posted", "Source"
]

RESULTS_COLUMNS = [
    "Title", "Company", "Link", "MatchScore",
    "SkillsMatch", "Location", "Worktype", "Seniority"
]

# ── Output ───────────────────────────────────────────────────
# Enable debug mode to save HTML snapshots
DEBUG_MODE = False

if DEBUG_MODE:
    DEBUG_DIR = DATA_DIR / "debug_output"
    DEBUG_DIR.mkdir(exist_ok=True)

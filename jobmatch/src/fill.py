# jobs_csv_full_updater.py
# Combined script:
# - Scrapes missing/empty "Description" from job Link
# - Extracts Skills (lowercase), Worktype, Seniority, EmploymentType
# - Works in-place on jobs.csv
# - Skips scraping (and delay) if Description already exists

import csv
import time
import random
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────
CSV_FILE = "./data/jobs.csv"  # input + output (updated in place)

# Scraping settings
MIN_DELAY = 8
MAX_DELAY = 16
TIMEOUT_GOTO = 45000
TIMEOUT_CARD = 25000
MAX_RETRIES = 2

# Column names (must match scraper)
DESCRIPTION_COL = "Description"
SKILLS_COL      = "Skills"
WORKTYPE_COL    = "Worktype"
SENIORITY_COL   = "Seniority"
EMPTYPE_COL     = "EmploymentType"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# ── Skill patterns (lowercase only) ─────────────
coding_patterns = [
    r'html[5]?', r'css[3]?', r'sass', r'scss', r'less',
    r'javascript', r'typescript', r'js', r'es6', r'es2015',
    r'react', r'react\.?js', r'next\.?js', r'react native',
    r'vue\.?js', r'vue', r'nuxt\.?js',
    r'angular', r'angularjs',
    r'svelte', r'sveltekit',
    r'tailwind', r'tailwindcss', r'bootstrap', r'material ui', r'mui',
    r'python', r'c', r'c\+\+', r'c#', r'java', r'ruby', r'php', r'go', r'rust',
    r'sql', r'mysql', r'ms sql', r'mssql', r'oracle', r'postgres', r'postgresql', r'mongodb', r'redis',
    r'node\.?js', r'django', r'flask', r'spring', r'laravel', r'express',
    r'graphql', r'apollo', r'relay',
    r'redux', r'react query', r'zustand', r'mobx',
    r'numpy', r'pandas', r'scikit\-learn', r'tensorflow', r'keras',
    r'sqlalchemy', r'beautifulsoup', r'requests',
    r'git', r'github', r'gitlab', r'docker', r'kubernetes', r'ci/cd', r'jenkins',
    r'webpack', r'vite', r'parcel', r'gulp', r'grunt', r'npm', r'yarn', r'pnpm',
]

# ── Worktype patterns ─────────────────────────────────────────────
worktype_patterns = {
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
    ]
}

# ── Seniority patterns ────────────────────────────────────────────
seniority_patterns = {
    "junior": [
        r'\bjunior|začiatočník|začínajúci|vývojár junior|programátor junior|junior level|entry level|0[-–]?[23] roky|do 23 rokov|bez skúseností|študent|student|absolvent\b',
    ],
    # "medior": [...],
    # "senior": [...],
}

# ── Employment type patterns ──────────────────────────────────────
emptype_patterns = {
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
    ]
}

# ────────────────────────────────────────────────
# FUNCTIONS
# ────────────────────────────────────────────────
def extract_skills(text: str) -> str:
    if not text or not isinstance(text, str):
        return "N/A"
    text_lower = text.lower()
    found = set()
    for pattern in coding_patterns:
        for match in re.findall(pattern, text_lower, re.IGNORECASE):
            clean = re.sub(r'[^a-z0-9\s\.]', '', match.strip())
            clean = re.sub(r'\s+', ' ', clean).strip()
            if len(clean) > 1:
                found.add(clean.lower())
    return ", ".join(sorted(found)) if found else "N/A"


def extract_category(text: str, patterns_dict: dict) -> str:
    if not text or not isinstance(text, str):
        return "N/A"
    text_lower = text.lower()
    candidates = []
    for category, patterns in patterns_dict.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                candidates.append(category)
                break
    if not candidates:
        return "N/A"
    # Priority rules
    if "senior" in candidates: return "senior"
    if "medior" in candidates: return "medior"
    if "junior" in candidates: return "junior"
    if "remote" in candidates: return "remote"
    if "hybrid" in candidates: return "hybrid"
    if "onsite" in candidates: return "onsite"
    if "fulltime" in candidates: return "fulltime"
    if "parttime" in candidates: return "parttime"
    return candidates[0]


def extract_card_text(page):
    try:
        page.wait_for_selector('.card.card-content', timeout=TIMEOUT_CARD)
        cards = page.query_selector_all('.card.card-content')
        if not cards:
            return ""
        text = cards[0].inner_text()
        text = " ".join(text.split())
        return text.strip()
    except PlaywrightTimeoutError:
        print(" → Timeout waiting for .card.card-content")
        return ""
    except Exception as e:
        print(f" → Error extracting text: {e}")
        return ""


def main():
    csv_path = Path(CSV_FILE)
    if not csv_path.is_file():
        print(f"File not found: {CSV_FILE}")
        return

    # ── SAFE READING OF CSV ──────────────────────────────────────
    rows = []
    original_fieldnames = []
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        original_fieldnames = reader.fieldnames or []
        line_num = 1
        for row in reader:
            line_num += 1
            if row is None:
                print(f"Line {line_num}: skipping None row")
                continue
            if not any(val.strip() for val in row.values()):
                print(f"Line {line_num}: skipping empty/whitespace row")
                continue
            rows.append(row)

    print(f"Loaded {len(rows)} valid-looking rows from CSV")

    # We do NOT add new columns here – we expect them to already exist
    fieldnames = original_fieldnames[:]  # keep existing columns

    updated_count = 0
    skipped_count = 0
    failed_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
            locale="sk-SK",
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()

        for i, row in enumerate(rows, 1):
            if row is None or not isinstance(row, dict):
                print(f"[{i:3d}] Skipping invalid row (None or not dict)")
                continue

            description = row.get(DESCRIPTION_COL, "").strip()

            if description:
                skipped_count += 1
                print(f"[{i:3d}] Skipping scrape (already has description)")
            else:
                url = row.get("Link", "").strip()
                if not url or not url.startswith("http"):
                    print(f"[{i:3d}] Skipping invalid/missing URL")
                    description = ""
                else:
                    print(f"[{i:3d}] Scraping description: {url}", end=" ... ", flush=True)
                    success = False
                    for attempt in range(1, MAX_RETRIES + 1):
                        try:
                            page.goto(url, wait_until="networkidle", timeout=TIMEOUT_GOTO)
                            page.wait_for_timeout(random.randint(1200, 3800))
                            description = extract_card_text(page)
                            row[DESCRIPTION_COL] = description
                            if description:
                                print("OK")
                            else:
                                print("no text found")
                            success = True
                            updated_count += 1
                            break
                        except Exception as e:
                            print(f"Attempt {attempt} failed: {e}")
                            if attempt < MAX_RETRIES:
                                time.sleep(random.uniform(5, 12))

                    if not success:
                        print(" → Giving up")
                        failed_count += 1
                        description = ""

                time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

            # Always update features
            row[SKILLS_COL] = extract_skills(description)
            row[WORKTYPE_COL] = extract_category(description, worktype_patterns)
            row[SENIORITY_COL] = extract_category(description, seniority_patterns)
            row[EMPTYPE_COL] = extract_category(description, emptype_patterns)

        browser.close()

    # ── Write back – keep all existing columns ───────────────────
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print("\n" + "="*60)
    print(f"Finished updating {CSV_FILE}")
    print(f" Scraped new descriptions   : {updated_count}")
    print(f" Skipped (already had desc) : {skipped_count}")
    print(f" Failed to scrape           : {failed_count}")
    print(f" All features saved back to : {csv_path.resolve()}")
    print("="*60)


if __name__ == "__main__":
    main()
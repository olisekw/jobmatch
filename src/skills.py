# Extract user profile from CV and preferences
# Creates user.csv with: Location, Skills, Seniority, Worktype
# REQUIRES: inputs.txt and resume.txt

import csv
import re
import sys
from pathlib import Path

# Import config
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

INPUT_TXT = config.INPUT_TXT
RESUME_TXT = config.RESUME_TXT
OUTPUT_CSV = config.USER_CSV

CSV_COLUMNS = ["Location", "Skills", "Seniority", "Worktype"]

# Skill detection patterns (case-insensitive)
CODING_PATTERNS = [
    r'html[5]?', r'css[3]?', r'sass', r'scss', r'less',
    r'javascript', r'typescript', r'js', r'es6', r'es2015',
    r'react', r'react\.?js', r'next\.?js', r'react native',
    r'vue\.?js', r'vue', r'nuxt\.?js',
    r'angular', r'angularjs',
    r'svelte', r'sveltekit',
    r'tailwind', r'tailwindcss', r'bootstrap', r'material ui', r'mui',
    r'python', r'c', r'c\+\+', r'c#', r'ruby', r'php', r'rust',
    r'sql', r'mysql', r'ms sql', r'mssql', r'oracle', r'postgres', r'postgresql', r'mongodb', r'redis',
    r'node\.?js', r'django', r'flask', r'spring', r'laravel', r'express',
    r'graphql', r'apollo', r'relay',
    r'redux', r'react query', r'zustand', r'mobx',
    r'numpy', r'pandas', r'scikit\-learn', r'tensorflow', r'keras',
    r'sqlalchemy', r'beautifulsoup', r'requests',
    r'git', r'github', r'gitlab', r'docker', r'kubernetes', r'ci/cd', r'jenkins',
    r'webpack', r'vite', r'parcel', r'gulp', r'grunt', r'npm', r'yarn', r'pnpm',
    r'mendix', r'power ?bi', r'business central', r'dynamics 365',r'flutter',r'firebase',
]

# Location detection patterns (Slovak cities)
LOCATION_PATTERN = r"(bratislava|ba|košice|kosice|ke|košický|žilina|nitra|trnava|prešov|banská bystrica)"
SENIORITY_PATTERN = r"(junior|medior|senior|začiatočník|začínajúci|stredne pokročilý|skúsený|absolvent|entry level|mid level)"
WORKTYPE_PATTERN = r"(remote|fully remote|100% remote|práca z domu|home ?office|work from home|hybrid|hybridný|kombinovaný režim|onsite|v kancelárii|office|na pracovisku)"

def extract_skills(text: str) -> str:
    """Extract recognized skills from text."""
    if not text.strip():
        return "N/A"
    text_lower = text.lower()
    found = set()
    for pattern in CODING_PATTERNS:
        for match in re.findall(pattern, text_lower, re.IGNORECASE):
            clean = re.sub(r'[^a-z0-9\s\.]', '', match.strip())
            clean = re.sub(r'\s+', ' ', clean).strip()
            if len(clean) > 1:
                nice = ' '.join(w.capitalize() for w in clean.split())
                found.add(nice)
    return ", ".join(sorted(found)) if found else "N/A"


def guess_category(text: str, pattern: str, mapping: dict) -> str:
    """Extract category from text using pattern and mapping."""
    if not text:
        return "N/A"
    text_lower = text.lower()
    m = re.search(pattern, text_lower, re.I)
    if m:
        found = m.group(0).lower()
        for key, words in mapping.items():
            if any(w in found for w in words):
                return key
    return "N/A"


def parse_inputs(file_path: Path) -> dict:
    """Parse user preferences from inputs.txt."""
    row = {col: "N/A" for col in CSV_COLUMNS}

    if not file_path.is_file():
        print(f"\nERROR: {INPUT_TXT} not found!")
        print("Create inputs.txt with your job preferences:")
        print("  Bratislava")
        print("  Senior")
        print("  Remote")
        print("  React, TypeScript, Node.js")
        sys.exit(1)

    text = file_path.read_text(encoding="utf-8").strip().lower()
    items = re.split(r'[,\n;]|alebo|or|\s*[,;]\s*', text)
    items = [item.strip() for item in items if item.strip()]

    for item in items:
        if re.search(LOCATION_PATTERN, item):
            row["Location"] = item.title()
            continue
        if re.search(SENIORITY_PATTERN, item):
            if "senior" in item:
                row["Seniority"] = "senior"
            elif "medior" in item or "stredne" in item or "mid" in item:
                row["Seniority"] = "medior"
            else:
                row["Seniority"] = "junior"
            continue
        if re.search(WORKTYPE_PATTERN, item):
            if "remote" in item or "z domu" in item or "home office" in item:
                row["Worktype"] = "remote"
            elif "hybrid" in item:
                row["Worktype"] = "hybrid"
            else:
                row["Worktype"] = "onsite"
            continue

    return row


def main():
    """Extract user profile and save to user.csv."""
    inputs_path = Path(INPUT_TXT)
    resume_path = Path(RESUME_TXT)

    # Check required files exist
    if not resume_path.is_file():
        print(f"\nERROR: {RESUME_TXT} not found!")
        print("Run pdf_to_txt.py first to convert cv.pdf to resume.txt")
        sys.exit(1)

    # Parse inputs (required)
    row = parse_inputs(inputs_path)

    # Load resume
    resume_text = resume_path.read_text(encoding="utf-8").strip()
    print(f"Resume loaded: {len(resume_text)} characters")

    # Fill missing fields from resume
    if row["Skills"] == "N/A" and resume_text:
        row["Skills"] = extract_skills(resume_text)

    mapping_work = {"remote": ["remote", "z domu", "home"], "hybrid": ["hybrid"], "onsite": ["office", "kancelárii"]}
    mapping_sen = {"junior": ["junior", "zač"], "medior": ["medior", "mid"], "senior": ["senior"]}

    if row["Seniority"] == "N/A" and resume_text:
        row["Seniority"] = guess_category(resume_text, SENIORITY_PATTERN, mapping_sen)

    if row["Worktype"] == "N/A" and resume_text:
        row["Worktype"] = guess_category(resume_text, WORKTYPE_PATTERN, mapping_work)

    out_path = Path(OUTPUT_CSV)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerow(row)

    print("\n" + "="*60)
    print("user.csv created:")
    for col, val in row.items():
        print(f"  {col:12} : {val}")
    print("="*60)
    print(f"File saved: {out_path.resolve()}")


if __name__ == "__main__":
    main()
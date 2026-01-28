# extract_features_from_description_csv.py
# Extracts: Skills (now lowercase) + Worktype + Seniority + EmploymentType from Description
# Returns "N/A" when nothing is found

import csv
import re
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────
INPUT_CSV       = "description.csv"             # your input file
OUTPUT_CSV      = "jobs_with_features.csv"      # result file
DESCRIPTION_COL = "Description"                 # column with job text

SKILLS_COL      = "Skills"
WORKTYPE_COL    = "Worktype"                    # remote / hybrid / onsite
SENIORITY_COL   = "Seniority"                   # junior / medior / senior
EMPTYPE_COL     = "EmploymentType"              # fulltime / parttime / ...

# ── Skill patterns (your original + some CZ/SK common ones) ───────
coding_patterns = [
    # Front-end
    r'html[5]?', r'css[3]?', r'sass', r'scss', r'less',
    r'javascript', r'typescript', r'js', r'es6', r'es2015',
    r'react', r'react\.?js', r'next\.?js', r'react native',
    r'vue\.?js', r'vue', r'nuxt\.?js',
    r'angular', r'angularjs',
    r'svelte', r'sveltekit',
    r'tailwind', r'tailwindcss', r'bootstrap', r'material ui', r'mui',
    # Backend & general
    r'python', r'c', r'c\+\+', r'c#', r'java', r'ruby', r'php', r'go', r'rust',
    r'sql', r'mysql', r'ms sql', r'mssql', r'oracle', r'postgres', r'postgresql', r'mongodb', r'redis',
    r'node\.?js', r'django', r'flask', r'spring', r'laravel', r'express',
    r'graphql', r'apollo', r'relay',
    r'redux', r'react query', r'zustand', r'mobx',
    # Python ecosystem
    r'numpy', r'pandas', r'scikit\-learn', r'tensorflow', r'keras',
    r'sqlalchemy', r'beautifulsoup', r'requests',
    # DevOps / tools
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
        r'\bjunior|začiatočník|začínajúci|vývojár junior|programátor junior|junior level|entry level|0[-–]?[23] roky|do 2 rokov|bez skúseností|študent|absolvent\b',
    ],
    "medior": [
        r'\bmedior|stredne pokročilý|3[-–]?[56]? rokov|3[-–]5 rokov skúseností|mid level|medior level\b',
    ],
    "senior": [
        r'\bsenior|lead|vedúci vývojár|skúsený programátor|senior level|7[+] rokov|viac ako 6 rokov|expert|principal\b',
    ]
}

# ── Employment type patterns (improved fulltime detection) ────────
emptype_patterns = {
    "fulltime": [
        r'\b(pln[ýy] ?úvaz(e|ek|ku|ok)|plny ?uvaz(e|ek|ku|ok))\b',
        r'\b(plný|plny) ?[úu]vaz(e|ek|ku|ok)\b',
        r'\b(full ?time|full-time|fulltime)\b',
        r'\b100% ?[úu]vaz(e|ek|ok)\b',
        r'\bHPP\b',
        r'\bhlavný ?pracovný ?pomer\b',
    ],
    "parttime": [
        r'\b(čiastočný ?úvaz(e|ek|ok)|ciastocny ?uvaz(e|ek|ok))\b',
        r'\b(part ?time|part-time|polovičný ?úvazok|polcasový ?úvazok|\d+[-–]hodinový úväzok)\b',
        r'\bbrigáda|DPP|DPČ|Dohoda o pracovnej činnosti|Dohoda o vykonaní práce|študentská práca\b',
    ],
    "internship": [
        r'\b(stáž|praxis|internship|absolventský program|trainee|odborná prax|študentská stáž)\b',
    ],
    "freelance": [
        r'\b(freelance|voľná noha|SZČO|živnosť|kontrakt|projektová spolupráca|self-employed)\b',
    ]
}

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
                # ← HERE: keep skill in lowercase (instead of capitalizing)
                found.add(clean.lower())
    
    if not found:
        return "N/A"
    
    # Sort and join with comma + space
    return ", ".join(sorted(found))


def extract_category(text: str, patterns_dict: dict) -> str:
    if not text or not isinstance(text, str):
        return "N/A"
    
    text_lower = text.lower()
    candidates = []
    
    for category, patterns in patterns_dict.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                candidates.append(category)
                break  # one match per category is enough
    
    if not candidates:
        return "N/A"
    
    # Priority rules when multiple matches
    if "senior" in candidates: return "senior"
    if "medior" in candidates: return "medior"
    if "junior" in candidates: return "junior"
    
    if "remote" in candidates: return "remote"
    if "hybrid" in candidates: return "hybrid"
    if "onsite" in candidates: return "onsite"
    
    if "fulltime" in candidates: return "fulltime"
    if "parttime" in candidates: return "parttime"
    
    return candidates[0]  # fallback


def main():
    input_path = Path(INPUT_CSV)
    if not input_path.is_file():
        print(f"Error: Input file not found → {INPUT_CSV}")
        return

    rows = []
    fieldnames = None

    with input_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames

        if DESCRIPTION_COL not in fieldnames:
            print(f"Error: Column '{DESCRIPTION_COL}' not found in CSV!")
            print("Available columns:", ", ".join(fieldnames))
            return

        # Add new columns if missing
        new_cols = [SKILLS_COL, WORKTYPE_COL, SENIORITY_COL, EMPTYPE_COL]
        for col in new_cols:
            if col not in fieldnames:
                fieldnames.append(col)

        for row in reader:
            desc = row.get(DESCRIPTION_COL, "").strip()

            row[SKILLS_COL]      = extract_skills(desc)
            row[WORKTYPE_COL]    = extract_category(desc, worktype_patterns)
            row[SENIORITY_COL]   = extract_category(desc, seniority_patterns)
            row[EMPTYPE_COL]     = extract_category(desc, emptype_patterns)

            rows.append(row)

    if not rows:
        print("No rows to process.")
        return

    # Write output CSV
    output_path = Path(OUTPUT_CSV)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print("Done!")
    print(f"Processed rows: {len(rows)}")
    print(f"Output saved to: {output_path.resolve()}")
    print("→ Skills column now contains only lowercase values")


if __name__ == "__main__":
    main()
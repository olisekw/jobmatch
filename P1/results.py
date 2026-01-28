# compare_user_to_jobs_seniority_only.py
# Filters ONLY by seniority match
# Calculates skills compatibility % → removes jobs below MIN_COMPATIBILITY → saves sorted results.csv

import pandas as pd

# ── CONFIGURATION ─────────────────────────────────────────────────
# Minimum compatibility percentage to keep a job
#   0   = keep everything with at least 1 matching skill
#  30   = keep only jobs where user matches at least 30% of required skills
#  50   = keep only jobs with 50%+ match (half or more skills)
# 100   = keep only perfect matches
MIN_COMPATIBILITY = 20  # ← change this number here

# ── File paths ────────────────────────────────────────────────────
USER_FILE    = "user.csv"                     # your preferences (1 row)
JOBS_FILE    = "jobs_with_features.csv"       # scraped jobs with features
RESULTS_FILE = "results.csv"                  # final output

# ── Load user preferences (single row) ────────────────────────────
try:
    user_df = pd.read_csv(USER_FILE)
    if len(user_df) == 0:
        raise ValueError("user.csv is empty")
    user = user_df.iloc[0]  # take first (and only) row
except Exception as e:
    print(f"Error loading user.csv: {e}")
    exit(1)

# ── Load jobs ─────────────────────────────────────────────────────
try:
    jobs_df = pd.read_csv(JOBS_FILE)
except Exception as e:
    print(f"Error loading jobs_with_features.csv: {e}")
    exit(1)

print(f"Loaded {len(jobs_df)} job offers")

# ── Normalize seniority for matching ──────────────────────────────
jobs_df['Seniority_norm'] = jobs_df['Seniority'].astype(str).str.lower().str.strip()
user_seniority = str(user.get('Seniority', '')).lower().strip()

# ── Filter: Seniority must match exactly (only filter applied) ─────
if user_seniority:
    jobs_df = jobs_df[jobs_df['Seniority_norm'] == user_seniority]
    print(f"After seniority filter: {len(jobs_df)} jobs remain")
else:
    print("No seniority specified in user.csv → showing all jobs")

# ── Skills compatibility % ────────────────────────────────────────
def skills_match_percentage(job_skills_str, user_skills_str):
    """
    Calculates how many of the job's required skills the user has.
    Returns percentage (0–100), rounded to 1 decimal place.
    """
    if pd.isna(job_skills_str) or not str(job_skills_str).strip():
        return 0.0

    # Split into clean sets (case-insensitive)
    job_set = {s.strip().lower() for s in str(job_skills_str).split(',') if s.strip()}
    user_set = {s.strip().lower() for s in str(user_skills_str).split(',') if s.strip()}

    if not job_set:
        return 0.0

    matched = job_set & user_set
    percentage = (len(matched) / len(job_set)) * 100
    return round(percentage, 1)

# Calculate compatibility for every remaining job
jobs_df['compatibility'] = jobs_df['Skills'].apply(
    lambda s: skills_match_percentage(s, user.get('Skills', ''))
)

# ── Remove jobs below minimum compatibility threshold ─────────────
jobs_df = jobs_df[jobs_df['compatibility'] >= MIN_COMPATIBILITY].copy()

print(f"After removing jobs below {MIN_COMPATIBILITY}% compatibility: {len(jobs_df)} jobs remain")

# ── Prepare final output ──────────────────────────────────────────
output_df = jobs_df[[
    'Company', 'Title', 'Freshness', 'compatibility', 'Link'
]].copy()

# Sort by compatibility descending (highest first)
output_df = output_df.sort_values('compatibility', ascending=False).reset_index(drop=True)

# Add rank column (1 = best match)
output_df.insert(0, 'Rank', range(1, len(output_df) + 1))

# Format compatibility as percentage string
output_df['compatibility'] = output_df['compatibility'].astype(str) + '%'

# ── Save and show preview ─────────────────────────────────────────
output_df.to_csv(RESULTS_FILE, index=False, encoding='utf-8')

print("\n" + "═" * 70)
print(f"Final results saved to: {RESULTS_FILE}")
print("═" * 70)


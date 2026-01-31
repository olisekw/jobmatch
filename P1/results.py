# compare_user_to_jobs_seniority_only.py
# Filters jobs where Status is NOT "x" and NOT "applied"
# Saves passing jobs (ranked) to results.csv
# Marks filtered-out jobs (among processed ones) with Status = "x"
# DOES NOT remove any jobs from jobs.csv

import pandas as pd
import sys
import re

# ── CONFIGURATION ─────────────────────────────────────────────────
MIN_COMPATIBILITY = 0  # minimum score to keep a job

# Jobs with these statuses are ignored / skipped (not processed, not re-marked)
IGNORED_STATUSES = {'x', 'applied'}

USER_FILE    = "user.csv"
JOBS_FILE    = "jobs.csv"
RESULTS_FILE = "results.csv"

# ── Load user preferences (single row) ────────────────────────────
try:
    user_df = pd.read_csv(USER_FILE)
    if len(user_df) == 0:
        raise ValueError("user.csv is empty")
    user = user_df.iloc[0]
except Exception as e:
    print(f"Error loading user.csv: {e}")
    sys.exit(1)

# ── Load jobs ─────────────────────────────────────────────────────
try:
    jobs_df = pd.read_csv(JOBS_FILE)
    print(f"Loaded {len(jobs_df)} job offers from {JOBS_FILE}")
except Exception as e:
    print(f"Error loading {JOBS_FILE}: {e}")
    sys.exit(1)

# Initialize Status column if missing
if 'Status' not in jobs_df.columns:
    jobs_df['Status'] = ""

# ── Only process jobs where Status is NOT "x" or "applied" ────────
print(f"Total jobs: {len(jobs_df)}")
process_df = jobs_df[
    ~jobs_df['Status'].astype(str).str.strip().str.lower().isin(IGNORED_STATUSES)
].copy()

print(f"Jobs to process (Status not 'x' or 'applied'): {len(process_df)}")
print(f"Ignored jobs (Status = 'x' or 'applied'): {len(jobs_df) - len(process_df)}")

if len(process_df) == 0:
    print("No jobs to process (all have 'x' or 'applied'). Nothing to do.")
    sys.exit(0)

# ── Seniority filter (only on processable jobs) ───────────────────
process_df['Seniority_norm'] = process_df['Seniority'].astype(str).str.lower().str.strip()
user_seniority = str(user.get('Seniority', '')).lower().strip()

if user_seniority:
    original_process_count = len(process_df)
    process_df = process_df[process_df['Seniority_norm'] == user_seniority]
    print(f"After seniority filter: {len(process_df)} remain (was {original_process_count})")
else:
    print("No seniority → all processable jobs included")

# ── Skills compatibility % ────────────────────────────────────────
def skills_match_percentage(job_skills_str, user_skills_str):
    if pd.isna(job_skills_str) or not str(job_skills_str).strip():
        return 0.0

    job_set = {s.strip().lower() for s in str(job_skills_str).split(',') if s.strip()}
    user_set = {s.strip().lower() for s in str(user_skills_str).split(',') if s.strip()}

    if not job_set:
        return 0.0

    matched = job_set & user_set
    return round((len(matched) / len(job_set)) * 100, 1) if job_set else 0.0

process_df['compatibility'] = process_df['Skills'].apply(
    lambda s: skills_match_percentage(s, user.get('Skills', ''))
)

# ── Final passing jobs ────────────────────────────────────────────
passed_df = process_df[process_df['compatibility'] >= MIN_COMPATIBILITY].copy()

print(f"After compatibility filter: {len(passed_df)} remain")

# ── Prepare results.csv (only passing jobs) ───────────────────────
output_df = passed_df[[
    'Company', 'Title', 'Freshness', 'compatibility', 'Link'
]].copy()

output_df = output_df.sort_values('compatibility', ascending=False).reset_index(drop=True)
output_df.insert(0, 'Rank', range(1, len(output_df) + 1))
output_df['compatibility'] = output_df['compatibility'].astype(str) + '%'

output_df.to_csv(RESULTS_FILE, index=False)
print("\n" + "═" * 70)
print(f"Ranked passing jobs saved to: {RESULTS_FILE} ({len(output_df)} jobs)")
print("═" * 70)

# ── Mark filtered-out jobs (among processed) with "x" ─────────────
print("\nMarking filtered jobs in jobs.csv...")

# Normalize links for matching
jobs_df['Link_norm'] = jobs_df['Link'].astype(str).str.strip().str.lower()
passed_df['Link_norm'] = passed_df['Link'].astype(str).str.strip().str.lower()

passed_links = set(passed_df['Link_norm'])

# Mark only if:
# - was processed (not ignored originally)
# - did NOT pass
mask_mark = (
    ~jobs_df['Status'].astype(str).str.strip().str.lower().isin(IGNORED_STATUSES) &  # was not ignored
    ~jobs_df['Link_norm'].isin(passed_links)                                        # did not pass
)

jobs_df.loc[mask_mark, 'Status'] = "x"

count_marked = mask_mark.sum()
print(f"→ Marked {count_marked} jobs as 'x' (filtered out)")
print(f"→ Preserved status for {len(jobs_df) - count_marked} jobs")

# Cleanup temporary columns
temp_cols = ['Seniority_norm', 'Link_norm', 'compatibility']
jobs_df.drop(columns=[c for c in temp_cols if c in jobs_df.columns], inplace=True, errors='ignore')

# ── Save ALL jobs back ────────────────────────────────────────────
print(f"\nSaving {len(jobs_df)} jobs back to {JOBS_FILE}...")
jobs_df.to_csv(JOBS_FILE, index=False)

print(f"Updated (all jobs preserved): {JOBS_FILE}")
print(f" → {len(passed_df)} passed → in results.csv")
print(f" → {count_marked} newly filtered → Status = 'x'")
# declined.py
"""
Mark jobs as declined (no longer want to track as applied).

Usage:
  python declined.py 2 3
  python declined.py 1 4 5

Takes ranks from **applied.csv** (not results.csv!)
→ changes Status = "applied" → "x" in jobs.csv
→ removes those rows from applied.csv
"""

import sys
import pandas as pd
from pathlib import Path

JOBS_FILE    = "jobs.csv"
APPLIED_FILE = "applied.csv"

STATUS_DECLINED = "rejected"

def main():
    if len(sys.argv) < 2:
        print("Usage: python declined.py <rank1> <rank2> ...")
        print("Ranks refer to the current content of applied.csv")
        sys.exit(1)

    try:
        declined_ranks = {int(arg) for arg in sys.argv[1:]}
        print(f"Declined ranks: {sorted(declined_ranks)}")
    except ValueError:
        print("Error: Ranks must be integers")
        sys.exit(1)

    applied_path = Path(APPLIED_FILE)
    jobs_path    = Path(JOBS_FILE)

    if not applied_path.is_file():
        print(f"Error: {APPLIED_FILE} not found")
        sys.exit(1)
    if not jobs_path.is_file():
        print(f"Error: {JOBS_FILE} not found")
        sys.exit(1)

    print("Loading files...")
    applied_df = pd.read_csv(applied_path)
    jobs_df    = pd.read_csv(jobs_path)

    if 'Rank' not in applied_df.columns or 'Link' not in applied_df.columns:
        print(f"Error: {APPLIED_FILE} missing 'Rank' or 'Link'")
        sys.exit(1)
    if 'Link' not in jobs_df.columns:
        print(f"Error: {JOBS_FILE} missing 'Link'")
        sys.exit(1)

    # Normalize links
    applied_df['link_norm'] = applied_df['Link'].astype(str).str.strip().str.lower()
    jobs_df['link_norm']    = jobs_df['Link'].astype(str).str.strip().str.lower()

    if 'Status' not in jobs_df.columns:
        jobs_df['Status'] = ""

    removed_count = 0
    updated_count = 0

    for rank in declined_ranks:
        row = applied_df[applied_df['Rank'] == rank]
        if row.empty:
            print(f"Warning: Rank {rank} not found in {APPLIED_FILE}")
            continue

        link_norm = row['link_norm'].iloc[0]
        mask = jobs_df['link_norm'] == link_norm

        if mask.any():
            jobs_df.loc[mask, 'Status'] = STATUS_DECLINED
            updated_count += 1
            print(f"  → Rank {rank} → '{STATUS_DECLINED}'")
        else:
            print(f"Warning: Link for rank {rank} not found in jobs.csv")

    # Remove selected rows from applied.csv
    keep_mask = ~applied_df['Rank'].isin(declined_ranks)
    applied_df = applied_df[keep_mask].copy()

    removed_count = len(declined_ranks) - (len(declined_ranks) - keep_mask.sum())

    # Drop helper
    applied_df = applied_df.drop(columns=['link_norm'], errors='ignore')
    jobs_df    = jobs_df.drop(columns=['link_norm'], errors='ignore')

    # Save both
    applied_df.to_csv(APPLIED_FILE, index=False, encoding='utf-8')
    jobs_df.to_csv(JOBS_FILE, index=False, encoding='utf-8')

    print("\n" + "═"*60)
    print("Finished processing declines")
    print(f"  → Changed to '{STATUS_DECLINED}': {updated_count}")
    print(f"  → Removed from applied.csv: {removed_count}")
    print(f"  → Saved: {JOBS_FILE}")
    print(f"  → Saved: {APPLIED_FILE}")
    print("═"*60)

if __name__ == "__main__":
    main()
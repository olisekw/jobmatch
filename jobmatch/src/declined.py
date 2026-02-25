"""
declined.py
Mark jobs as rejected and remove them from applied.csv

Usage:
    python declined.py 3 7 12
    → moves those ranks from applied.csv back to jobs.csv with Status = "rejected"
    → removes them from applied.csv
    → ranks 2 and 3 (if not mentioned) remain in applied.csv

Requires:
- applied.csv has columns: Rank (or Applied_Rank), Link, ...
- jobs.csv has columns: Link, Status, ...
"""
import sys
import pandas as pd
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────
DATA_DIR = Path("./data")
JOBS_FILE   = DATA_DIR / "jobs.csv"
APPLIED_FILE = DATA_DIR / "applied.csv"

STATUS_REJECTED = "rejected"          # or "x" if you prefer
RANK_COLUMN = "Rank"          # change to "Rank" if you use that name

# ─────────────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {Path(__file__).name} <rank1> <rank2> ...")
        print(f"       Ranks refer to the '{RANK_COLUMN}' column in {APPLIED_FILE}")
        sys.exit(1)

    try:
        declined_ranks = {int(arg) for arg in sys.argv[1:]}
        print(f"Declining ranks: {sorted(declined_ranks)}")
    except ValueError:
        print("Error: All arguments must be integers")
        sys.exit(1)

    applied_path = Path(APPLIED_FILE)
    jobs_path = Path(JOBS_FILE)

    if not applied_path.is_file():
        print(f"Error: {APPLIED_FILE} not found")
        sys.exit(1)
    if not jobs_path.is_file():
        print(f"Error: {JOBS_FILE} not found")
        sys.exit(1)

    print("Loading files...")
    applied_df = pd.read_csv(applied_path)
    jobs_df = pd.read_csv(jobs_path)

    if RANK_COLUMN not in applied_df.columns:
        print(f"Error: {APPLIED_FILE} is missing column '{RANK_COLUMN}'")
        sys.exit(1)
    if 'Link' not in applied_df.columns:
        print(f"Error: {APPLIED_FILE} missing 'Link'")
        sys.exit(1)
    if 'Link' not in jobs_df.columns:
        print(f"Error: {JOBS_FILE} missing 'Link'")
        sys.exit(1)

    # Normalize links (recommended even if case-sensitive)
    applied_df['link_norm'] = applied_df['Link'].astype(str).str.strip().str.lower()
    jobs_df['link_norm']    = jobs_df['Link'].astype(str).str.strip().str.lower()

    if 'Status' not in jobs_df.columns:
        jobs_df['Status'] = ""

    updated_count = 0
    removed_count = 0

    for rank in declined_ranks:
        row = applied_df[applied_df[RANK_COLUMN] == rank]
        if row.empty:
            print(f"Warning: {RANK_COLUMN} {rank} not found in {APPLIED_FILE}")
            continue

        link_norm = row['link_norm'].iloc[0]
        mask = jobs_df['link_norm'] == link_norm

        if mask.any():
            jobs_df.loc[mask, 'Status'] = STATUS_REJECTED
            updated_count += mask.sum()
            print(f"  → {RANK_COLUMN} {rank} → Status = '{STATUS_REJECTED}'")
        else:
            print(f"Warning: No matching job found in jobs.csv for {RANK_COLUMN} {rank}")

        # Remove from applied_df
        applied_df = applied_df[applied_df[RANK_COLUMN] != rank]
        removed_count += 1

    # Cleanup helper column
    applied_df = applied_df.drop(columns=['link_norm'], errors='ignore')
    jobs_df    = jobs_df.drop(columns=['link_norm'], errors='ignore')

    # Save
    applied_df.to_csv(APPLIED_FILE, index=False, encoding='utf-8')
    jobs_df.to_csv(JOBS_FILE, index=False, encoding='utf-8')

    print("\n" + "═" * 60)
    print("Finished processing declines")
    print(f" → Jobs updated to '{STATUS_REJECTED}': {updated_count}")
    print(f" → Removed from applied.csv  : {removed_count}")
    print(f" → Saved: {JOBS_FILE}")
    print(f" → Saved: {APPLIED_FILE}")
    print("═" * 60)


if __name__ == "__main__":
    main()
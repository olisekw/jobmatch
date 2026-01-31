# choose.py
"""
Select jobs to apply to from results.csv.

After choosing:
- Selected jobs   → Status = "applied" in jobs.csv
- Non-selected jobs from results.csv → Status = "x"
- Selected jobs   → appended to applied.csv
- results.csv     → becomes EMPTY (always overwritten with 0 rows, even if no selection)
"""

import sys
import pandas as pd
from pathlib import Path

# Files
JOBS_FILE     = "jobs.csv"
RESULTS_FILE  = "results.csv"
APPLIED_FILE  = "applied.csv"

# Status values
STATUS_APPLIED   = "applied"
STATUS_DISCARDED = "x"

def main():
    if len(sys.argv) < 2:
        print("Usage: python choose.py <rank1> [rank2] [rank3] ...")
        print("Examples:")
        print("  python choose.py 2 3")
        print("  python choose.py 1 4 5")
        print("  python choose.py 0   # discard all in results.csv → empty file")
        sys.exit(1)

    try:
        selected_ranks = {int(x) for x in sys.argv[1:]}
        print(f"→ Selected ranks: {sorted(selected_ranks)}")
    except ValueError:
        print("Error: All arguments must be integers")
        sys.exit(1)

    # ── Check files ────────────────────────────────────────────────
    results_path = Path(RESULTS_FILE)
    jobs_path    = Path(JOBS_FILE)
    applied_path = Path(APPLIED_FILE)

    if not results_path.is_file():
        print(f"Error: {RESULTS_FILE} not found")
        sys.exit(1)
    if not jobs_path.is_file():
        print(f"Error: {JOBS_FILE} not found")
        sys.exit(1)

    print("Loading files...")
    results_df = pd.read_csv(results_path)
    jobs_df    = pd.read_csv(jobs_path)

    if not {'Rank', 'Link'}.issubset(results_df.columns):
        print(f"Error: {RESULTS_FILE} missing 'Rank' or 'Link'")
        sys.exit(1)
    if 'Link' not in jobs_df.columns:
        print(f"Error: {JOBS_FILE} missing 'Link'")
        sys.exit(1)

    # Normalize links
    results_df['link_norm'] = results_df['Link'].astype(str).str.strip().str.lower()
    jobs_df['link_norm']    = jobs_df['Link'].astype(str).str.strip().str.lower()

    if 'Status' not in jobs_df.columns:
        jobs_df['Status'] = ""

    # ── 1. Mark EVERY job currently in results.csv as "x" (discard) ──
    discarded_count = 0
    for link_norm in results_df['link_norm']:
        mask = (jobs_df['link_norm'] == link_norm)
        if mask.any():
            jobs_df.loc[mask, 'Status'] = STATUS_DISCARDED
            discarded_count += mask.sum()

    print(f"→ Set {discarded_count} jobs to '{STATUS_DISCARDED}' (all in results.csv)")

    # ── 2. Override selected ranks → "applied" + collect for applied.csv ─
    applied_rows = []
    applied_count = 0

    for rank in selected_ranks:
        match = results_df[results_df['Rank'] == rank]
        if match.empty:
            print(f"Warning: Rank {rank} not found → skipped")
            continue

        link_norm = match['link_norm'].iloc[0]

        job_mask = (jobs_df['link_norm'] == link_norm)
        if job_mask.any():
            jobs_df.loc[job_mask, 'Status'] = STATUS_APPLIED
            applied_count += 1
            applied_rows.append(match.iloc[0].to_dict())
            print(f"  → Rank {rank} → '{STATUS_APPLIED}'")
        else:
            print(f"Warning: Link for rank {rank} not found in jobs.csv")

    # ── 3. Append selected to applied.csv (only new ones) ──────────
    if applied_rows:
        new_applied = pd.DataFrame(applied_rows)

        if applied_path.is_file():
            old = pd.read_csv(applied_path)
            if 'Link' in old.columns:
                existing = set(old['Link'].astype(str).str.strip().str.lower())
                new_applied = new_applied[~new_applied['Link'].astype(str).str.strip().str.lower().isin(existing)]
            combined = pd.concat([old, new_applied], ignore_index=True)
        else:
            combined = new_applied

        combined.to_csv(APPLIED_FILE, index=False)
        print(f"→ Added {len(new_applied)} new job(s) to {APPLIED_FILE}")
    else:
        print("→ No jobs selected → applied.csv unchanged")

    # ── 4. ALWAYS empty results.csv ────────────────────────────────
    empty_df = pd.DataFrame(columns=results_df.columns)
    empty_df.to_csv(RESULTS_FILE, index=False)
    print(f"→ Emptied {RESULTS_FILE} (now has 0 rows)")

    # ── 5. Save updated jobs.csv ───────────────────────────────────
    jobs_df = jobs_df.drop(columns=['link_norm'], errors='ignore')
    jobs_df.to_csv(JOBS_FILE, index=False)
    print(f"→ Saved updated {JOBS_FILE}")

    print("\n" + "═" * 70)
    print("Summary:")
    print(f"  Applied   : {applied_count}")
    print(f"  Discarded : {discarded_count}")
    print(f"  results.csv now : empty")
    print("═" * 70)


if __name__ == "__main__":
    main()
"""
choose.py
Single-prompt job selector

- Shows results.csv with temporary ranks (1,2,3,... per batch)
- One line input: ranks you WANT to apply to (space separated)
- If empty or "0" → all jobs in this batch → "x" (none applied)
- Selected → "applied" in jobs.csv + added to applied.csv (no rank column)
- Unselected → "x" in jobs.csv
- Prevents exact duplicate links in applied.csv
- Clears results.csv afterwards
"""

import sys
import pandas as pd
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
JOBS_FILE    = DATA_DIR / "jobs.csv"
RESULTS_FILE = DATA_DIR / "results.csv"
APPLIED_FILE = DATA_DIR / "applied.csv"

STATUS_APPLIED   = "applied"
STATUS_DISCARDED = "x"


def print_results_table() -> bool:
    if not RESULTS_FILE.is_file() or RESULTS_FILE.stat().st_size == 0:
        print("\n" + "═" * 80)
        print(" results.csv is empty or missing ")
        print("═" * 80 + "\n")
        return False

    try:
        df = pd.read_csv(RESULTS_FILE)
    except Exception as e:
        print(f"Error reading results.csv: {e}")
        return False

    print("\n" + "═" * 80)
    print(" Current batch (temporary ranks – valid only this run)")
    print("═" * 80)

    if df.empty:
        print("(only header – no jobs)")
        print("═" * 80 + "\n")
        return False

    cols = [c for c in ['Rank', 'Title', 'Company', 'Location', 'Salary', 'match_score', 'Seniority', 'Link']
            if c in df.columns]
    if not cols:
        cols = df.columns.tolist()

    display_df = df[cols].copy()
    if 'Link' in display_df.columns:
        display_df['Link'] = display_df['Link'].apply(lambda x: str(x)[:60] + '…' if len(str(x)) > 60 else str(x))

    print(display_df.to_string(index=False))
    print("═" * 80 + "\n")
    return True


def main():
    if not print_results_table():
        print("No jobs to select → exiting.\n")
        return

    print("Enter ranks you WANT to apply to (space separated)")
    print("  • empty line or 0 → skip everything (all → 'x')")
    print("  • example: 1 3 5   → apply to 1,3,5  → others 'x'")
    print("One line only.\n")

    try:
        results_df = pd.read_csv(RESULTS_FILE)
        jobs_df    = pd.read_csv(JOBS_FILE)
    except Exception as e:
        print(f"Error reading files: {e}")
        sys.exit(1)

    if not {'Rank', 'Link'}.issubset(results_df.columns):
        print("Error: results.csv missing 'Rank' or 'Link'")
        sys.exit(1)
    if 'Link' not in jobs_df.columns:
        print("Error: jobs.csv missing 'Link'")
        sys.exit(1)

    if 'Status' not in jobs_df.columns:
        jobs_df['Status'] = ""

    # Default: mark everything in this batch as discarded
    discarded = 0
    for link in results_df['Link'].unique():
        mask = jobs_df['Link'] == link
        if mask.any():
            jobs_df.loc[mask, 'Status'] = STATUS_DISCARDED
            discarded += mask.sum()

    print(f"→ All {discarded} job(s) marked '{STATUS_DISCARDED}' by default\n")

    # ── Single input ────────────────────────────────────────────────────────
    line = input("→ ").strip()

    selected_ranks = set()
    if line and line != "0":
        for part in line.split():
            try:
                selected_ranks.add(int(part))
            except ValueError:
                print(f"Ignored invalid: {part}")

    # ── Apply selection ─────────────────────────────────────────────────────
    selected_rows = []
    applied_count = 0

    for rank in selected_ranks:
        match = results_df[results_df['Rank'] == rank]
        if match.empty:
            print(f"Rank {rank} not found")
            continue

        link = match['Link'].iloc[0]
        mask = jobs_df['Link'] == link

        if mask.any():
            jobs_df.loc[mask, 'Status'] = STATUS_APPLIED
            selected_rows.append(match.iloc[0].to_dict())
            applied_count += 1
            print(f"✓ {rank} → applied")
        else:
            print(f"Rank {rank}: link not found in jobs.csv")

    # ── Save applied ────────────────────────────────────────────────────────
    if selected_rows:
        to_add = pd.DataFrame(selected_rows)

        # Deduplicate by exact link
        if APPLIED_FILE.is_file() and APPLIED_FILE.stat().st_size > 0:
            old = pd.read_csv(APPLIED_FILE)
            existing = set(old['Link'])
            to_add = to_add[~to_add['Link'].isin(existing)]

        if not to_add.empty:
            mode = 'a' if APPLIED_FILE.is_file() else 'w'
            header = not APPLIED_FILE.is_file()
            to_add.to_csv(APPLIED_FILE, mode=mode, header=header, index=False)
            print(f"\n→ Added {len(to_add)} new job(s) to applied.csv")
        else:
            print("\n→ No new jobs (already in applied.csv)")

    else:
        print("\n→ No jobs selected → all marked 'x'")

    # ── Cleanup ─────────────────────────────────────────────────────────────
    pd.DataFrame(columns=results_df.columns).to_csv(RESULTS_FILE, index=False)
    jobs_df.to_csv(JOBS_FILE, index=False)

    print(f"→ Cleared {RESULTS_FILE}")
    print(f"→ Updated {JOBS_FILE}")

    print("\n" + "═" * 60)
    print(f"Applied   : {applied_count}")
    print(f"Rejected  : {discarded - applied_count}")
    print("═" * 60)


if __name__ == "__main__":
    main()
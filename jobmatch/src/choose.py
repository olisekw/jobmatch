"""
choose.py
Interactive job selector - single prompt version

Behavior:
- Shows results.csv with temporary ranks
- One single input line expected
- Enter space-separated ranks you WANT to apply to
- If input is empty or "0" → all jobs marked "x", nothing added to applied.csv
- Otherwise → selected ranks → "applied" + added to applied.csv
- All non-selected ranks in this batch → "x"
- Prevents duplicate exact Links in applied.csv
- Clears results.csv after processing
"""
import sys
import pandas as pd
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent  # jobmatch/
DATA_DIR = BASE_DIR / "data"
JOBS_FILE = DATA_DIR / "jobs.csv"
RESULTS_FILE = DATA_DIR / "results.csv"
APPLIED_FILE = DATA_DIR / "applied.csv"

STATUS_APPLIED = "applied"
STATUS_DISCARDED = "x"


def print_results_table() -> bool:
    """Prints nice table and returns True if there are jobs to choose from"""
    if not RESULTS_FILE.is_file() or RESULTS_FILE.stat().st_size == 0:
        print("\n" + "═" * 100)
        print(" Current content of results.csv ")
        print("═" * 100)
        print("(file is missing or completely empty)")
        print("═" * 100 + "\n")
        return False

    try:
        df = pd.read_csv(RESULTS_FILE)
    except Exception as e:
        print(f"Error reading results.csv: {e}")
        return False

    print("\n" + "═" * 100)
    print(" Current content of results.csv  (temporary ranks — valid only this session)")
    print("═" * 100)

    if df.empty:
        print("(file has only header — no jobs)")
        print("═" * 100 + "\n")
        return False

    preferred = ['Rank', 'Title', 'Company', 'Location', 'Salary', 'match_score', 'Seniority', 'Link']
    cols = [c for c in preferred if c in df.columns]
    if not cols:
        cols = df.columns.tolist()

    display_df = df[cols].copy()
    if 'Link' in display_df.columns:
        display_df['Link'] = display_df['Link'].apply(
            lambda x: str(x)[:68] + '…' if len(str(x)) > 68 else str(x)
        )

    print(display_df.to_string(index=False))
    print("═" * 100 + "\n")
    return True


def main():
    has_jobs = print_results_table()
    if not has_jobs:
        print("No jobs available to select → exiting cleanly.\n")
        return

    print("Enter the ranks you WANT to apply to (space separated numbers)")
    print("  • empty line or 0 → mark ALL as 'x' (skip everything)")
    print("  • example: 1 3 4  → apply to 1,3,4  → others get 'x'")
    print("One line only. Press Enter after typing.\n")

    try:
        results_df = pd.read_csv(RESULTS_FILE)
        jobs_df = pd.read_csv(JOBS_FILE)
    except Exception as e:
        print(f"Error reading input files: {e}")
        sys.exit(1)

    if not {'Rank', 'Link'}.issubset(results_df.columns):
        print("Error: results.csv missing 'Rank' or 'Link'")
        sys.exit(1)
    if 'Link' not in jobs_df.columns:
        print("Error: jobs.csv missing 'Link'")
        sys.exit(1)

    if 'Status' not in jobs_df.columns:
        jobs_df['Status'] = ""

    # ── Mark ALL as discarded by default ────────────────────────────────────
    discarded_count = 0
    applied_count = 0
    for link in results_df['Link'].unique():
        mask = (jobs_df['Link'] == link)
        if mask.any():
            jobs_df.loc[mask, 'Status'] = STATUS_DISCARDED
            discarded_count += mask.sum()

    print(f"→ All {discarded_count} job(s) temporarily marked as '{STATUS_DISCARDED}'")

    # ── Single input ─────────────────────────────────────────────────────────
    try:
        line = input("→ ").strip()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return

    selected_ranks = set()

    if line and line != "0":
        for part in line.split():
            try:
                rank = int(part)
                selected_ranks.add(rank)
            except ValueError:
                print(f" Ignored invalid: {part}")
                continue

    # ── Process selection ────────────────────────────────────────────────────
    selected_rows = []
    selected_links = set()

    for rank in selected_ranks:
        match = results_df[results_df['Rank'] == rank]
        if match.empty:
            print(f" Rank {rank} not found → ignored")
            continue

        link = match['Link'].iloc[0]
        if link in selected_links:
            print(f" Rank {rank} already processed → skipped")
            continue

        job_mask = (jobs_df['Link'] == link)
        if job_mask.any():
            jobs_df.loc[job_mask, 'Status'] = STATUS_APPLIED
            selected_links.add(link)

            row = match.iloc[0].to_dict()
            selected_rows.append(row)

            applied_count += 1
            print(f" ✓ {rank} → applied")
        else:
            print(f" Rank {rank}: link not found in jobs.csv → ignored")

    # If nothing was selected (0 or empty), everything stays "x"
    if not selected_rows:
        print("\n→ No jobs selected → all marked as 'x'")

    # ── Save to applied.csv (only if something was selected) ─────────────────
    if selected_rows:
        to_add = pd.DataFrame(selected_rows)

        # Prevent duplicates by exact Link
        if APPLIED_FILE.is_file() and APPLIED_FILE.stat().st_size > 0:
            old = pd.read_csv(APPLIED_FILE)
            existing = set(old['Link'])
            to_add = to_add[~to_add['Link'].isin(existing)]

        if not to_add.empty:
            mode = 'a' if APPLIED_FILE.is_file() else 'w'
            header = not APPLIED_FILE.is_file() or old.empty
            to_add.to_csv(APPLIED_FILE, mode=mode, header=header, index=False)
            print(f"\n→ Added {len(to_add)} new job(s) to applied.csv")
        else:
            print("\n→ No new jobs (all selected already exist in applied.csv)")

    # ── Cleanup ──────────────────────────────────────────────────────────────
    pd.DataFrame(columns=results_df.columns).to_csv(RESULTS_FILE, index=False)
    print(f"→ Cleared {RESULTS_FILE}")

    jobs_df.to_csv(JOBS_FILE, index=False)
    print(f"→ Updated {JOBS_FILE} with Status")

    print("\n" + "═" * 70)
    print("Summary:")
    print(f"  Applied     : {applied_count}")
    print(f"  Marked 'x'  : {discarded_count - applied_count}")
    print("═" * 70)


if __name__ == "__main__":
    main()
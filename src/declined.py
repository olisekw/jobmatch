"""
declined.py
Shows current applied.csv with temporary numbers 1..n (WITHOUT showing links or location)
You type which ones to decline → removed from applied.csv + Status = "rejected" in jobs.csv
Remaining jobs stay in applied.csv unchanged (no renumbering)
"""

import sys
import pandas as pd
from pathlib import Path

DATA_DIR = Path("./data")
JOBS_FILE    = DATA_DIR / "jobs.csv"
APPLIED_FILE = DATA_DIR / "applied.csv"

STATUS_REJECTED = "rejected"


def show_applied_list():
    if not APPLIED_FILE.is_file() or APPLIED_FILE.stat().st_size == 0:
        print("applied.csv is empty or missing.")
        sys.exit(0)

    try:
        df = pd.read_csv(APPLIED_FILE)
    except Exception as e:
        print(f"Cannot read applied.csv: {e}")
        sys.exit(1)

    if 'Link' not in df.columns:
        print("applied.csv missing 'Link' column – cannot continue.")
        sys.exit(1)

    print("\n" + "═" * 100)
    print(" Current applied jobs (temporary numbers for this run)")
    print("═" * 100)

    # Preferred columns to show – no Location, no Salary
    preferred_cols = ['Title', 'Company', 'match_score']
    display_cols = [c for c in preferred_cols if c in df.columns]

    if not display_cols:
        # Fallback: show everything except Link, Location, Salary
        display_cols = [c for c in df.columns if c not in ['Link', 'Location', 'Salary']]

    display = df[display_cols].copy().reset_index()
    display['#'] = display.index + 1
    display = display[['#'] + display_cols]

    # Shorten long text for better table readability
    for col in ['Title', 'Company']:
        if col in display.columns:
            display[col] = display[col].apply(
                lambda x: str(x)[:60] + '…' if len(str(x)) > 60 else str(x)
            )

    # Dynamic col_space – only include keys that actually exist in columns
    col_space_dict = {
        '#': 5,
        'Title': 65,
        'Company': 45,
    }
    # Add match_score spacing only if the column is present
    if 'match_score' in display.columns:
        col_space_dict['match_score'] = 12

    print(display.to_string(
        index=False,
        col_space=col_space_dict,
        justify='left',
        na_rep='–'
    ))

    print("═" * 100 + "\n")


def main():
    show_applied_list()

    print("Enter the temporary numbers of jobs you want to DECLINE (space separated)")
    print("Example: 1 3  → those jobs → rejected + removed from applied.csv")
    print("Empty line or Ctrl+C → do nothing and exit\n")

    try:
        line = input("→ ").strip()
    except KeyboardInterrupt:
        print("\nCancelled.")
        return

    if not line:
        print("Nothing selected → exiting.")
        return

    try:
        to_decline = {int(x) for x in line.split()}
    except ValueError:
        print("Only numbers allowed.")
        return

    try:
        applied = pd.read_csv(APPLIED_FILE)
        jobs   = pd.read_csv(JOBS_FILE)
    except Exception as e:
        print(f"Error reading files: {e}")
        return

    if 'Link' not in applied.columns or 'Link' not in jobs.columns:
        print("Missing 'Link' in one of the files.")
        return

    if 'Status' not in jobs.columns:
        jobs['Status'] = ""

    removed = 0
    updated = 0

    # Temporary 1-based index for user selection
    applied = applied.reset_index(drop=True)
    applied['temp_idx'] = applied.index + 1

    for num in to_decline:
        row = applied[applied['temp_idx'] == num]
        if row.empty:
            print(f"Number {num} not found")
            continue

        link = row['Link'].iloc[0]
        mask = jobs['Link'] == link

        if mask.any():
            jobs.loc[mask, 'Status'] = STATUS_REJECTED
            updated += 1
            print(f"→ #{num} → marked 'rejected' in jobs.csv")

        # Remove from applied
        applied = applied[applied['temp_idx'] != num]
        removed += 1

    # Clean up temp column and save
    applied.drop(columns=['temp_idx'], inplace=True, errors='ignore')

    applied.to_csv(APPLIED_FILE, index=False)
    jobs.to_csv(JOBS_FILE, index=False)

    print("\n" + "═" * 50)
    print(f"Removed from applied.csv     : {removed}")
    print(f"Marked rejected in jobs.csv : {updated}")
    print("═" * 50)


if __name__ == "__main__":
    main()
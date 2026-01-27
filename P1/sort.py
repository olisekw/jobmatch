import csv
import os
import re

# CONFIG – change only if needed
INPUT_FILE = "jobs.csv"      # your input CSV
OUTPUT_FILE = "sorted_jobs.csv"

# Keywords (case-insensitive)

# LOCATION_KEYWORD = "bratislava"  # will match Košice, kosice, KOŠICE, etc.

# Freshness patterns for today / yesterday / last 7 days
FRESHNESS_PATTERNS = [
    r'\bdnes\b',                          # Dnes / Dnes ráno / Dnes popoludní
    r'\bvčera\b',                         # Včera
    r'pred\s+1\s+dňom\b',                 # Pred 1 dňom
    r'pred\s+(2|3|4|5|6|7)\s+dňami\b',    # Pred 2–7 dňami
    r'pred\s+(menej\s+ako\s+1\s+hodinou|1\s+hodinou|[1-9]?\d+\s+hodinami?)\b',  # Pred X hodinami
    r'pred\s+[1-5]?\d+\s+minútami?\b',    # Pred X minútami
]



# def matches_location(location):
#     if not location:
#         return False
#     return LOCATION_KEYWORD in location.lower()

def matches_recent(freshness):
    if not freshness:
        return False
    freshness_lower = freshness.lower()
    for pattern in FRESHNESS_PATTERNS:
        if re.search(pattern, freshness_lower):
            return True
    return False

def filter_kosice_junior_recent():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Input file not found → {INPUT_FILE}")
        return

    count = 0

    with open(INPUT_FILE, newline='', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames

        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as outfile:
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()

            for row in reader:
                title = row.get("Title", "").strip()
                location = row.get("Location", "").strip()
                freshness = row.get("Freshness", "").strip()

                # if  matches_location(location):
                writer.writerow(row)
                count += 1

    print(f"Done!")
    print(f"Found and saved {count} jobs matching ALL conditions:")
    print(f"  • Title contains 'junior', 'student' or 'trainee'")
    print(f"  • Location contains 'Košice'")
    print(f"  • Posted today, yesterday or in last 7 days")
    if count > 0:
        print(f"Output saved → {os.path.abspath(OUTPUT_FILE)}")
        print("You can now open it in Excel / Numbers / Google Sheets.")
    else:
        print("No matching jobs found.")
        print("Possible reasons:")
        print(" - No jobs in Košice with these titles")
        print(" - Freshness wording is different (paste 3–5 examples)")
        print(" - Location is written differently (e.g. 'Košický kraj' instead of 'Košice')")

if __name__ == "__main__":
    filter_kosice_junior_recent()
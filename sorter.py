import csv
import os
import re

# CONFIG
INPUT_CSV = "profesia_sk_python_jobs.csv"             # your original file
OUTPUT_FILE = "jobs_pred_4_dnami.csv"                 # new filtered file

# Pattern for "pred 4 dňami" (case-insensitive, allows minor variations)
PATTERN = r'pred\s+4\s+dňami\b'

def is_pred_4_dnami(freshness):
    if not freshness or freshness.strip() == "":
        return False
    return bool(re.search(PATTERN, freshness.lower()))

def filter_pred_4_dnami():
    if not os.path.exists(INPUT_CSV):
        print(f"Error: Input file '{INPUT_CSV}' not found!")
        return

    count = 0

    with open(INPUT_CSV, newline='', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames

        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as outfile:
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()

            for row in reader:
                freshness = row.get("Freshness", "").strip()
                if is_pred_4_dnami(freshness):
                    writer.writerow(row)
                    count += 1

    print(f"Done!")
    print(f"Found and saved {count} jobs with 'pred 4 dňami' in Freshness.")
    if count > 0:
        print(f"New file created: {os.path.abspath(OUTPUT_FILE)}")
    else:
        print("No jobs with 'pred 4 dňami' found.")
        print("Check your CSV — paste 3–5 exact 'Freshness' values if nothing matched.")

if __name__ == "__main__":
    filter_pred_4_dnami()
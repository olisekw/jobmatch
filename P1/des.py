# scrape_card_text_per_job_headless.py
# Reads sorted_jobs.csv → adds Description column → writes descriptions_with_data.csv
# Keeps ALL original columns + new Description column

import csv
import time
import random
import os
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ── Configuration ────────────────────────────────────────────────
INPUT_CSV     = "jobs.csv"
OUTPUT_CSV    = "description.csv"   # better name than just descriptions.csv
MIN_DELAY     = 9
MAX_DELAY     = 17
TIMEOUT_GOTO  = 45000
TIMEOUT_CARD  = 20000
# ─────────────────────────────────────────────────────────────────

def extract_card_text(page):
    try:
        page.wait_for_selector('.card.card-content', timeout=TIMEOUT_CARD)
        cards = page.query_selector_all('.card.card-content')
        if not cards:
            return ""
        # Take first card (most common pattern), clean & lowercase
        text = cards[0].inner_text()
        text = " ".join(text.split())   # normalize spaces
        return text.strip().lower()
    except PlaywrightTimeoutError:
        print("  → Timeout waiting for .card.card-content")
        return ""
    except Exception as e:
        print(f"  → Error extracting text: {e}")
        return ""

def main():
    if not os.path.exists(INPUT_CSV):
        print(f"Input file not found: {INPUT_CSV}")
        return

    # Read fieldnames from input CSV
    with open(INPUT_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        input_fieldnames = reader.fieldnames

    # We will add one new column
    output_fieldnames = input_fieldnames + ["Description"]

    processed = 0
    failed = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--no-sandbox"])
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="sk-SK",
            viewport={"width": 1280, "height": 800},
        )

        # Optional: helps some sites detect less obviously
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        page = context.new_page()

        # We'll write output incrementally (safer on long runs)
        with open(OUTPUT_CSV, "w", newline='', encoding="utf-8") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=output_fieldnames)
            writer.writeheader()

            with open(INPUT_CSV, newline='', encoding='utf-8') as infile:
                reader = csv.DictReader(infile)

                for row in reader:
                    processed += 1
                    url = row.get("Link", "").strip()

                    if not url or not url.startswith("http"):
                        print(f"[{processed:3d}] Skipping invalid URL: {url}")
                        row["Description"] = ""
                        writer.writerow(row)
                        continue

                    print(f"[{processed:3d}] {url}", end=" ... ", flush=True)

                    try:
                        page.goto(url, wait_until="networkidle", timeout=TIMEOUT_GOTO)
                        page.wait_for_timeout(random.randint(1200, 3800))  # small human-like wait

                        description = extract_card_text(page)
                        row["Description"] = description

                        if description:
                            print("OK")
                        else:
                            print("no card text found")

                        writer.writerow(row)

                    except Exception as e:
                        failed += 1
                        print(f"FAILED → {e}")
                        row["Description"] = ""
                        writer.writerow(row)

                    # Be nice to the server
                    sleep_time = random.uniform(MIN_DELAY, MAX_DELAY)
                    time.sleep(sleep_time)

        browser.close()

    print("=" * 15)
    print(f"Finished processing {processed} ")
    print("=" * 15)

if __name__ == "__main__":
    main()
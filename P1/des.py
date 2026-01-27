# scrape_card_text_per_job_headless.py
# This script runs in the background (headless browser),
# extracts ONLY the clean text from elements with class="card card-content",
# and saves each job as its own CSV file: 1.csv, 2.csv, 3.csv, ...

import csv
import time
import random
import os
from playwright.sync_api import sync_playwright

# Configuration
INPUT_CSV = "sorted_jobs.csv"                          # Your input file with "Link" column
OUTPUT_FOLDER = "descriptions"                      # Folder for 1.csv, 2.csv, ...

# Delay between pages (seconds) to avoid blocking
MIN_DELAY = 8
MAX_DELAY = 18

def extract_card_text(page):
    """
    Extract all clean text from the element with class="card card-content".
    Returns plain readable text only (no tags).
    """
    try:
        # Wait for the card to appear (up to 25 seconds)
        page.wait_for_selector('.card.card-content', timeout=25000)

        # Get all matching cards (usually one main card)
        cards = page.query_selector_all('.card.card-content')

        if cards:
            # Take the first (main) card's text
            main_card = cards[0]
            raw_text = main_card.inner_text()

            # Clean: remove extra spaces/newlines
            clean_text = " ".join(raw_text.split())
            clean_text = clean_text.replace("  ", " ").strip()

            return clean_text
        else:
            return "NO CARD WITH CLASS 'card card-content' FOUND ON PAGE"

    except Exception as e:
        print(f"  → Extraction error: {e}")
        return f"ERROR EXTRACTING CARD TEXT: {str(e)}"


def main():
    if not os.path.exists(INPUT_CSV):
        print(f"Error: Input file not found → {INPUT_CSV}")
        return

    # Create output folder
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    print(f"Reading input: {INPUT_CSV}")
    print("Running in headless mode (no browser window visible)")

    with open(INPUT_CSV, newline='', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)

        with sync_playwright() as p:
            # Headless browser - no window opens
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0",
                viewport={"width": 1280, "height": 900},
                locale="sk-SK",
            )
            page = context.new_page()

            for row_number, row in enumerate(reader, start=1):
                url = row.get("Link", "").strip()
                if not url:
                    print(f"Row {row_number} → No Link, skipping")
                    continue

                print(f"[{row_number}] Processing: {url}")

                try:
                    page.goto(url, wait_until="networkidle", timeout=60000)
                    page.wait_for_timeout(4000)  # Extra wait for JS to load content

                    card_text = extract_card_text(page)

                    output_row = {
                        "Link": url,
                        "card_text": card_text
                    }

                    filename = os.path.join(OUTPUT_FOLDER, f"{row_number}.csv")
                    with open(filename, 'w', newline='', encoding='utf-8') as outfile:
                        writer = csv.DictWriter(outfile, fieldnames=["Link", "card_text"])
                        writer.writeheader()
                        writer.writerow(output_row)

                    print(f"  → Saved: {filename} ({len(card_text)} characters)")

                except Exception as e:
                    print(f"  → Error: {e}")
                    output_row = {"Link": url, "card_text": "FAILED TO LOAD OR EXTRACT CARD"}
                    filename = os.path.join(OUTPUT_FOLDER, f"{row_number}.csv")
                    with open(filename, 'w', newline='', encoding='utf-8') as outfile:
                        writer = csv.DictWriter(outfile, fieldnames=["Link", "card_text"])
                        writer.writeheader()
                        writer.writerow(output_row)

                time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

            browser.close()

    print("\nFinished!")
    print(f"Processed all links from {INPUT_CSV}")
    print(f"Individual CSV files saved in: {os.path.abspath(OUTPUT_FOLDER)}")
    print("Each file contains only the link and clean text from class='card card-content'.")


if __name__ == "__main__":
    main()
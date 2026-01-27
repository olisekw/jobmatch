# scrape_card_text_per_job_headless.py
# Outputs:
# link description (all lowercase)

import csv
import time
import random
import os
from playwright.sync_api import sync_playwright

INPUT_CSV = "sorted_jobs.csv"
OUTPUT_TXT = "descriptions.txt"

MIN_DELAY = 8
MAX_DELAY = 18


def extract_card_text(page):
    try:
        page.wait_for_selector('.card.card-content', timeout=25000)
        cards = page.query_selector_all('.card.card-content')

        if cards:
            return " ".join(cards[0].inner_text().split()).strip().lower()
        else:
            return ""

    except Exception:
        return ""


def main():
    if not os.path.exists(INPUT_CSV):
        print(f"Missing input file: {INPUT_CSV}")
        return

    with open(INPUT_CSV, newline='', encoding='utf-8') as infile, \
         open(OUTPUT_TXT, "a", encoding="utf-8") as outfile:

        reader = csv.DictReader(infile)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                locale="sk-SK",
            )
            page = context.new_page()

            for idx, row in enumerate(reader, start=1):
                url = row.get("Link", "").strip()
                if not url:
                    continue

                print(f"extracting page {idx}")

                try:
                    page.goto(url, wait_until="networkidle", timeout=60000)
                    page.wait_for_timeout(4000)

                    text = extract_card_text(page)
                    outfile.write(f"{url} {text}\n")

                except Exception as e:
                    print(f"failed page {idx}: {e}")
                    outfile.write(f"{url}\n")

                time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

            browser.close()


if __name__ == "__main__":
    main()

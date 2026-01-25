import csv
import time
import random
import os
from playwright.sync_api import sync_playwright

# CONFIG
INPUT_CSV = "jobs_pred_4_dnami.csv"      # ← your file
OUTPUT_CSV = "profesia_detailed_jobs_playwright.csv"

MAX_PAGES = 10  # safety limit – increase if needed

# ────────────────────────────────────────────────
def extract_job_details(page):
    """Extract text from loaded page using Playwright selectors"""
    data = {}

    try:
        # Wait for main content to appear
        page.wait_for_selector("div.offer-detail__description, div.detail-description", timeout=15000)

        # Full description
        desc = page.query_selector("div.offer-detail__description, div.detail-description")
        data["full_description"] = desc.inner_text().strip() if desc else ""

        # Responsibilities / Náplň práce
        resp = page.query_selector_all("h2, h3, strong")
        for el in resp:
            text = el.inner_text().lower()
            if "náplň práce" in text or "povinnosti" in text or "čo budete robiť" in text:
                section = el.evaluate_handle("el => el.parentElement")
                data["responsibilities"] = section.inner_text().strip()
                break
        data["responsibilities"] = data.get("responsibilities", "")

        # Requirements / Požiadavky
        for el in resp:
            text = el.inner_text().lower()
            if "požiadavky" in text or "očakávame" in text or "ideálny kandidát" in text:
                section = el.evaluate_handle("el => el.parentElement")
                data["requirements"] = section.inner_text().strip()
                break
        data["requirements"] = data.get("requirements", "")

        # Offers / Ponúkame
        for el in resp:
            text = el.inner_text().lower()
            if "ponúkame" in text or "výhody" in text or "benefit" in text:
                section = el.evaluate_handle("el => el.parentElement")
                data["offers"] = section.inner_text().strip()
                break
        data["offers"] = data.get("offers", "")

        # Salary detail (if different)
        salary = page.query_selector("span.salary__value, .salary-detail")
        data["salary_detail"] = salary.inner_text().strip() if salary else ""

    except Exception as e:
        print(f"Extraction error: {e}")
        data["full_description"] = "EXTRACTION FAILED"

    return data


# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────

def main():
    if not os.path.exists(INPUT_CSV):
        print(f"Input file not found: {INPUT_CSV}")
        return

    all_rows = []
    processed = 0

    with open(INPUT_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames + ["full_description", "responsibilities", "requirements", "offers", "salary_detail"]

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)  # change to False to watch
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 1024},
                locale="sk-SK",
            )
            page = context.new_page()

            for row in reader:
                url = row.get("Link", "").strip()
                if not url:
                    continue

                print(f"[{processed+1}] Fetching: {url}")
                try:
                    page.goto(url, wait_until="networkidle", timeout=45000)
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(3000)  # extra wait for JS

                    details = extract_job_details(page)
                    row.update(details)
                    processed += 1
                except Exception as e:
                    print(f"  → Error: {e}")
                    row["full_description"] = "FAILED TO LOAD"
                    processed += 1  # count anyway

                all_rows.append(row)

                time.sleep(random.uniform(8, 15))  # polite delay

            browser.close()

    # Save
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nDone! Processed {processed} jobs.")
    print(f"Saved to: {os.path.abspath(OUTPUT_CSV)}")


if __name__ == "__main__":
    main()
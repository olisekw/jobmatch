import csv
import time
import random
import re
from urllib.parse import urljoin, quote_plus
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup

# ────────────────────────────────────────────────
# CONFIG – change these values here only
# ────────────────────────────────────────────────
BASE_URL = "https://sk.jooble.org/praca/"
SEARCH_TERM = "programator"          # ← change freely (e.g. "python", "junior developer")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
OUTPUT_FILE = "jobs_jooble.csv"             # appends to existing file
MAX_PAGES = 2                       # start small (1–3), then increase
# ────────────────────────────────────────────────
# LOAD PAGE WITH RETRY
# ────────────────────────────────────────────────
@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1.5, min=8, max=60),
    retry=retry_if_exception_type(PlaywrightTimeoutError),
    reraise=True
)
def load_page(page, url, pg_num):
    print(f"→ Page {pg_num}: {url}")
    resp = page.goto(url, wait_until="networkidle", timeout=65000)
    if resp is None or resp.status >= 400:
        raise RuntimeError(f"Bad status: {resp.status if resp else 'no response'}")
    page.wait_for_timeout(random.randint(3000, 8000))  # human-like delay
    return page.content()

# ────────────────────────────────────────────────
# PARSE JOBS FROM JOOBLE.SK HTML – ALL TEXT LOWERCASE
# ────────────────────────────────────────────────
def parse_jobs(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_urls = set()

    # Job cards are usually inside <article> or <div class="_card">
    job_cards = soup.find_all("article", class_="_card")  # main job card class on Jooble
    if not job_cards:
        print(" → No job cards found – possible layout change / block / anti-bot")
        return jobs

    for card in job_cards:
        # Link & Title
        title_link = card.find("a", class_="_3mfro")
        if not title_link:
            continue

        href = title_link.get("href", "")
        if not href:
            continue

        full_link = urljoin(base_url, href)
        if full_link in seen_urls:
            continue
        seen_urls.add(full_link)

        title = title_link.get_text(strip=True).lower()

        # Company
        company_tag = card.find("span", class_="_3mfro _9fXTd")
        company = company_tag.get_text(strip=True).lower() if company_tag else "n/a"

        # Location
        loc_tag = card.find("span", class_="_3mfro _2W2iI")
        location = loc_tag.get_text(strip=True).lower() if loc_tag else "n/a"

        # Salary
        salary_tag = card.find("span", class_="_3mfro _2Wp8I Z6b3y")
        salary = salary_tag.get_text(strip=True).lower() if salary_tag else "n/a"

        # Freshness / Date
        date_tag = card.find("span", class_="_3mfro _1ZlLP")
        freshness = date_tag.get_text(strip=True).lower() if date_tag else "n/a"

        jobs.append({
            "Title": title,
            "Company": company,
            "Location": location,
            "Salary": salary,
            "Freshness": freshness,
            "Link": full_link,
        })

    return jobs

# ────────────────────────────────────────────────
# MAIN – APPEND ONLY NEW JOBS (based on Link uniqueness)
# ────────────────────────────────────────────────
def main(max_pages=MAX_PAGES, output_file=OUTPUT_FILE):
    all_new_jobs = []
    existing_urls = set()

    output_path = Path(output_file)

    # 1. Load existing job URLs to avoid duplicates
    if output_path.is_file():
        print(f"Existing file found: {output_file} → loading URLs to skip duplicates...")
        with output_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                link = row.get("Link", "").strip()
                if link:
                    existing_urls.add(link)

        print(f"→ Found {len(existing_urls)} existing unique jobs")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # ← False for debugging
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 1024},
            locale="sk-SK",
            timezone_id="Europe/Bratislava",
        )
        page = context.new_page()

        print("Navigating to sk.jooble.org...")
        page.goto(BASE_URL, wait_until="networkidle", timeout=45000)

        # Interactive search
        try:
            print(f"Performing search: '{SEARCH_TERM}'")
            search_input = page.wait_for_selector(
                "input[placeholder*='Pozícia' i], "
                "input[placeholder*='Hľadať' i], "
                "input[name='q'], input[type='search'], "
                "input[aria-label*='hľadať' i]",
                timeout=30000
            )
            search_input.fill(SEARCH_TERM)
            search_input.press("Enter")
            page.wait_for_load_state("networkidle", timeout=40000)
            print(" → Search results loaded")
        except Exception as e:
            print(f" → Interactive search failed: {e}")
            # Fallback direct URL
            encoded = quote_plus(SEARCH_TERM)
            search_url = f"{BASE_URL}{encoded}"
            print(f" → Using direct URL: {search_url}")
            page.goto(search_url, wait_until="networkidle", timeout=45000)

        current_url = page.url

        for pg in range(1, max_pages + 1):
            if pg > 1:
                separator = "&" if "?" in current_url else "?"
                url = f"{current_url}{separator}page={pg}"
            else:
                url = current_url

            try:
                html = load_page(page, url, pg)
                page_jobs = parse_jobs(html, BASE_URL)
                print(f" → Page {pg} → {len(page_jobs)} jobs found")

                # Filter out already known jobs
                new_jobs = [job for job in page_jobs if job["Link"] not in existing_urls]
                print(f"   → {len(new_jobs)} new unique jobs")

                all_new_jobs.extend(new_jobs)

                # Update known URLs
                for job in new_jobs:
                    existing_urls.add(job["Link"])

            except Exception as e:
                print(f" → FAILED page {pg}: {e}")
                break

            if pg < max_pages:
                time.sleep(random.uniform(10, 22))  # polite delay

        browser.close()

    # ── Append new jobs to CSV (create if not exists) ─────────────
    if all_new_jobs:
        keys = ["Title", "Company", "Location", "Salary", "Freshness", "Link"]

        file_exists = output_path.is_file()
        mode = "a" if file_exists else "w"

        with output_path.open(mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)

            if not file_exists:
                writer.writeheader()

            writer.writerows(all_new_jobs)

        total_jobs = len(existing_urls) + len(all_new_jobs)
        print(f"\nDone! Appended {len(all_new_jobs)} new jobs")
        print(f"Total unique jobs in file now: {total_jobs}")
        print(f"File: {output_path.resolve()}")
    else:
        print("\nNo new jobs found to append.")
        if output_path.is_file():
            print(f"Existing file unchanged: {output_path.resolve()}")
        else:
            print("No file created (no jobs scraped).")

if __name__ == "__main__":
    # Remember:
    # pip install playwright tenacity beautifulsoup4 lxml
    # playwright install
    main(max_pages=MAX_PAGES)
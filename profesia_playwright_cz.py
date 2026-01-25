import csv
import time
import random
import re
import os
from urllib.parse import urljoin, quote
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup

# ────────────────────────────────────────────────
# CONFIG – change values here only
# ────────────────────────────────────────────────

BASE_URL = "https://www.profesia.cz/prace/"
SEARCH_TERM = "python"                           # ← Change this to anything (e.g. "python", "java")
SORT_BY = "relevance"                                 # can be "validity_from", "salary_desc", etc.

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEBUG_DIR = "debug_pages_profesia_cz"
OUTPUT_FILE = f"profesia_cz_{SEARCH_TERM.replace(' ', '_')}_jobs.csv"

MAX_PAGES = 2  # start small – increase later

# Auto-create debug folder
os.makedirs(DEBUG_DIR, exist_ok=True)

# ────────────────────────────────────────────────
# LOAD PAGE WITH RETRY
# ────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1.5, min=8, max=60),
    retry=retry_if_exception_type(PlaywrightTimeoutError),
)
def load_page(page, url, pg_num):
    print(f"→ Page {pg_num}: {url}")
    resp = page.goto(url, wait_until="networkidle", timeout=65000)
    if resp is None or resp.status >= 400:
        raise RuntimeError(f"Bad status: {resp.status if resp else 'no response'}")

    try:
        page.wait_for_selector("ul.list li.list-row", timeout=35000)
        print(" → Job listings detected")
    except PlaywrightTimeoutError:
        print(" → No jobs after wait – possible block / layout change / empty page")

    page.wait_for_timeout(random.randint(3000, 8000))  # human-like pause
    html = page.content()

    debug_file = os.path.join(DEBUG_DIR, f"debug_page_{pg_num}.html")
    with open(debug_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f" → Debug saved: {debug_file}")

    return html


# ────────────────────────────────────────────────
# PARSE JOBS FROM HTML
# ────────────────────────────────────────────────

def parse_jobs(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_ids = set()

    list_container = soup.find("ul", class_="list")
    if not list_container:
        print(" → No <ul class='list'> found – possible block or site change")
        return jobs

    for li in list_container.find_all("li", class_="list-row"):
        if "promo-tile" in li.get("class", []):
            continue

        title_a = li.find("h2").find("a") if li.find("h2") else None
        if not title_a:
            continue

        offer_id = title_a.get("id", "").replace("offer", "")
        if not offer_id or offer_id in seen_ids:
            continue
        seen_ids.add(offer_id)

        href = title_a.get("href", "")
        if not href or "/prace/" not in href:
            continue

        full_link = urljoin(base_url, href)

        title_span = title_a.find("span", class_="title")
        title = title_span.get_text(strip=True) if title_span else title_a.get_text(strip=True)

        company_span = li.find("span", class_="employer")
        company = company_span.get_text(strip=True) if company_span else "N/A"

        loc_span = li.find("span", class_="job-location")
        location = loc_span.get_text(strip=True) if loc_span else "N/A"
        loc_title = loc_span.get("title", "").strip() if loc_span else ""
        if loc_title and loc_title != location:
            location = f"{location} ({loc_title})"

        # Salary – flexible for Czech
        salary = "N/A"
        sal_span = li.find("span", class_=re.compile(r"label.*green|label.*salary|label.*money"))
        if sal_span:
            text = sal_span.get_text(strip=True).replace("\xa0", " ").strip()
            if any(c.isdigit() for c in text):
                salary = text

        fresh_span = li.find("span", class_="info")
        freshness = fresh_span.get_text(strip=True) if fresh_span else "N/A"

        jobs.append({
            "Title": title,
            "Company": company,
            "Location": location,
            "Salary": salary,
            "Freshness": freshness,
            "Link": full_link,
            "Offer_ID": offer_id,
        })

    print(f" → Extracted {len(jobs)} valid jobs")
    return jobs


# ────────────────────────────────────────────────
# MAIN – SEARCH + PAGINATION WITH CORRECT PARAMS
# ────────────────────────────────────────────────

def main(max_pages=MAX_PAGES, output_file=OUTPUT_FILE):
    all_jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # set False to watch
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 1024},
            locale="cs-CZ",
            timezone_id="Europe/Prague",
        )
        page = context.new_page()

        print("Navigating to profesia.cz...")
        page.goto(BASE_URL, wait_until="networkidle", timeout=45000)

        # Perform search using the real parameter
        try:
            print(f"Performing search: '{SEARCH_TERM}'")
            search_input = page.wait_for_selector(
                "input[placeholder*='Pozice' i], "
                "input[placeholder*='Hledat' i], "
                "input[name='q'], input[name='search_anywhere'], "
                "input[type='search'], "
                "input[aria-label*='hledat' i]",
                timeout=30000
            )
            search_input.fill(SEARCH_TERM)
            search_input.press("Enter")

            page.wait_for_load_state("networkidle", timeout=40000)
            print(" → Search results loaded")
        except Exception as e:
            print(f" → Search failed: {e}")
            # Fallback: manually build search URL if selector misses
            search_url = f"{BASE_URL}?search_anywhere={quote(SEARCH_TERM)}&sort_by=relevance"
            print(f" → Falling back to direct URL: {search_url}")
            page.goto(search_url, wait_until="networkidle", timeout=45000)

        # Scrape pages using correct pagination (?page_num=)
        current_url = page.url
        for pg in range(1, max_pages + 1):
            if pg > 1:
                separator = "&" if "?" in current_url else "?"
                url = f"{current_url}{separator}page_num={pg}"
            else:
                url = current_url

            try:
                html = load_page(page, url, pg)
                page_jobs = parse_jobs(html, BASE_URL)
                print(f" → Page {pg} → {len(page_jobs)} jobs")
                all_jobs.extend(page_jobs)
            except Exception as e:
                print(f" → FAILED page {pg}: {e}")
                break

            time.sleep(random.uniform(10, 22))  # polite delay

        browser.close()

    # Save to CSV
    if all_jobs:
        keys = ["Title", "Company", "Location", "Salary", "Freshness", "Link", "Offer_ID"]
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_jobs)
        print(f"\nDone! Saved {len(all_jobs)} jobs for '{SEARCH_TERM}' → {output_file}")
    else:
        print("\nNo jobs scraped. Check debug files in: {DEBUG_DIR}")
        print("Likely causes: anti-bot block (CAPTCHA/Cloudflare), changed selectors, or no results.")


if __name__ == "__main__":
    # Install dependencies once if needed:
    # pip install playwright tenacity beautifulsoup4 lxml
    # playwright install

    main(max_pages=2)
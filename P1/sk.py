import csv
import time
import random
import re
from urllib.parse import urljoin, quote, urlencode
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
from pathlib import Path

# ────────────────────────────────────────────────
# CONFIG – change these values here only
# ────────────────────────────────────────────────
BASE_URL = "https://www.profesia.sk/praca/"
SEARCH_TERMS = [
    "developer",
    "programator",
    "engineer",
    "student",
    # add more terms here if needed
]
SORT_BY = "relevance"
COUNT_DAYS = 1                      # last 24 hours
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
OUTPUT_FILE = "jobs.csv"
MAX_PAGES_PER_TERM = 2              # how many pages per search term
# ────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1.5, min=8, max=60),
    retry=retry_if_exception_type(PlaywrightTimeoutError),
    reraise=True
)
def load_page(page, url, pg_num, term):
    print(f"[{term}] → Page {pg_num}: {url}")
    resp = page.goto(url, wait_until="networkidle", timeout=65000)
    if resp is None or resp.status >= 400:
        raise RuntimeError(f"Bad status: {resp.status if resp else 'no response'}")
    page.wait_for_timeout(random.randint(3000, 8000))
    return page.content()

def parse_jobs(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_ids = set()
    list_container = soup.find("ul", class_="list")
    if not list_container:
        print(" → No <ul class='list'> found – possible layout change / block")
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
        if not href or "/praca/" not in href:
            continue
        full_link = urljoin(base_url, href)

        title = (
            title_a.find("span", class_="title").get_text(strip=True).lower()
            if title_a.find("span", class_="title")
            else title_a.get_text(strip=True).lower()
        )
        company = (
            li.find("span", class_="employer").get_text(strip=True).lower()
            if li.find("span", class_="employer")
            else "n/a"
        )
        loc_span = li.find("span", class_="job-location")
        location = loc_span.get_text(strip=True).lower() if loc_span else "n/a"
        loc_title = loc_span.get("title", "").strip().lower() if loc_span else ""
        if loc_title and loc_title != location:
            location = f"{location} ({loc_title})"

        salary = "n/a"
        sal_span = li.find("span", class_=re.compile(r"label.*(?:green|salary|money)"))
        if sal_span:
            text = sal_span.get_text(strip=True).replace("\xa0", " ").strip().lower()
            if any(c.isdigit() for c in text):
                salary = text

        freshness = (
            li.find("span", class_="info").get_text(strip=True).lower()
            if li.find("span", class_="info")
            else "n/a"
        )

        jobs.append({
            "Title": title,
            "Company": company,
            "Location": location,
            "Salary": salary,
            "Freshness": freshness,
            "Link": full_link,
            "Offer_ID": offer_id,
        })
    return jobs

def build_search_url(term, sort_by, count_days):
    params = {
        "search_anywhere": term,
        "sort_by": sort_by,
    }
    if count_days is not None:
        params["count_days"] = count_days

    # This is the correct way to build query string from dict
    return BASE_URL + "?" + urlencode(params)

def main(max_pages_per_term=MAX_PAGES_PER_TERM, output_file=OUTPUT_FILE):
    all_new_jobs = []
    existing_offer_ids = set()
    output_path = Path(output_file)

    # 1. Load existing jobs to avoid duplicates
    if output_path.is_file():
        print(f"Existing file found: {output_file} – loading to skip duplicates...")
        with output_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                offer_id = row.get("Offer_ID", "").strip()
                if offer_id:
                    existing_offer_ids.add(offer_id)
        print(f"→ Found {len(existing_offer_ids)} existing unique jobs")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # ← False for debugging
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 1024},
            locale="sk-SK",
            timezone_id="Europe/Bratislava",
        )
        page = context.new_page()

        for term in SEARCH_TERMS:
            print(f"\n{'═'*70}")
            print(f"Processing search term: {term!r}")
            print(f"{'═'*70}\n")

            # Go to base page
            page.goto(BASE_URL, wait_until="networkidle", timeout=45000)

            # Try interactive search (fallback to direct if fails)
            try:
                search_input = page.wait_for_selector(
                    "input[placeholder*='Pozícia' i], input[placeholder*='Hľadať' i], "
                    "input[name='q'], input[name='search_anywhere'], input[type='search'], "
                    "input[aria-label*='hľadať' i]",
                    timeout=25000
                )
                search_input.fill(term)
                search_input.press("Enter")
                page.wait_for_load_state("networkidle", timeout=40000)
                print(f"  Interactive search succeeded for '{term}'")
            except Exception as e:
                print(f"  Interactive search failed for '{term}': {e} → using direct URL")

            # Always use clean direct URL with count_days
            search_url = build_search_url(term, SORT_BY, COUNT_DAYS)
            print(f"  Loading: {search_url}")
            page.goto(search_url, wait_until="networkidle", timeout=60000)

            current_url = page.url

            for pg in range(1, max_pages_per_term + 1):
                url = current_url
                if pg > 1:
                    sep = "&" if "?" in current_url else "?"
                    url = f"{current_url}{sep}page_num={pg}"

                try:
                    html = load_page(page, url, pg, term)
                    page_jobs = parse_jobs(html, BASE_URL)
                    print(f"    Page {pg} → {len(page_jobs)} jobs found")

                    new_jobs = [j for j in page_jobs if j["Offer_ID"] not in existing_offer_ids]
                    print(f"    → {len(new_jobs)} new jobs")

                    all_new_jobs.extend(new_jobs)
                    for job in new_jobs:
                        existing_offer_ids.add(job["Offer_ID"])

                except Exception as e:
                    print(f"    FAILED page {pg} for '{term}': {e}")
                    break

                if pg < max_pages_per_term:
                    time.sleep(random.uniform(10, 22))

        browser.close()

    # ── Append all new jobs at once ──
    if all_new_jobs:
        keys = ["Title", "Company", "Location", "Salary", "Freshness", "Link", "Offer_ID"]
        file_exists = output_path.is_file()
        mode = "a" if file_exists else "w"
        with output_path.open(mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            if not file_exists:
                writer.writeheader()
            writer.writerows(all_new_jobs)

        total = len(existing_offer_ids)
        print(f"\nFinished all searches.")
        print(f"Appended {len(all_new_jobs)} new jobs this run")
        print(f"Total unique jobs in file now: {total}")
        print(f"File → {output_path.resolve()}")
    else:
        print("\nNo new jobs found across any term.")

if __name__ == "__main__":
    main()
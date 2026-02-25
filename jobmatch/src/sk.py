import csv
import time
import random
import re
from urllib.parse import urljoin, urlencode
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup

# ────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────


## 155line - change count days LAST SCAN 4FEB
BASE_URL = "https://www.profesia.sk/praca/"
SEARCH_TERMS = [
    "developer", "programator", "inzinier", "vývojár", "programmer",
    "software", "javascript", "react", "front", "fullstack", "native"
]
SORT_BY = "relevance"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
OUTPUT_FILE = "./data/jobs.csv"

# === NEW BEHAVIOR YOU REQUESTED ===
FORCE_LAST_DAY_WHEN_CSV_EXISTS = True      # ← if True and file exists → count_days=1

# Speed profile
MODE = "normal"  # or "fast"
if MODE == "fast":
    MIN_PAGE_DELAY = 1.8
    MAX_PAGE_DELAY = 4.5
    GOTO_EXTRA_WAIT_MS = 400
    TIMEOUT = 32000
    RETRY_COUNT = 3
    print("Mode: FAST")
else:
    MIN_PAGE_DELAY = 5.5
    MAX_PAGE_DELAY = 13.0
    GOTO_EXTRA_WAIT_MS = 2000
    TIMEOUT = 50000
    RETRY_COUNT = 5
    print("Mode: NORMAL")

# ────────────────────────────────────────────────
@retry(
    stop=stop_after_attempt(RETRY_COUNT),
    wait=wait_exponential(multiplier=1.2, min=3, max=25),
    retry=retry_if_exception_type(PlaywrightTimeoutError),
    reraise=True
)
def load_page(page, url, pg_num, term):
    print(f"[{term}] Page {pg_num}: {url}")
    resp = page.goto(url, wait_until="networkidle", timeout=TIMEOUT)
    if resp is None or resp.status >= 400:
        raise RuntimeError(f"Bad status: {resp.status if resp else 'no response'}")
    page.wait_for_timeout(random.randint(GOTO_EXTRA_WAIT_MS, GOTO_EXTRA_WAIT_MS + 1800))
    return page.content()

def parse_jobs(html, base_url, search_term_lower, existing_offer_ids):
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_ids = set()
    matched_count = 0
    skipped_count = 0

    list_container = soup.find("ul", class_="list")
    if not list_container:
        return jobs, 0, 0

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

        if offer_id in existing_offer_ids:
            skipped_count += 1
            continue

        href = title_a.get("href", "")
        if not href or "/praca/" not in href:
            continue

        full_link = urljoin(base_url, href)

        title_span = title_a.find("span", class_="title")
        title = (title_span.get_text(strip=True).lower()
                 if title_span else title_a.get_text(strip=True).lower())

        if search_term_lower not in title:
            continue

        matched_count += 1

        company = li.find("span", class_="employer").get_text(strip=True).lower() \
            if li.find("span", class_="employer") else "n/a"

        loc_span = li.find("span", class_="job-location")
        location = loc_span.get_text(strip=True).lower() if loc_span else "n/a"
        loc_title = loc_span.get("title", "").strip().lower() if loc_span else ""
        if loc_title and loc_title != location:
            location = f"{location} ({loc_title})"

        salary = "n/a"
        sal_span = li.find("span", class_=re.compile(r"label.*(?:green|salary|money|plat|mzda)"))
        if sal_span:
            text = sal_span.get_text(strip=True).replace("\xa0", " ").strip().lower()
            if any(c.isdigit() for c in text):
                salary = text

        freshness = li.find("span", class_="info").get_text(strip=True).lower() \
            if li.find("span", class_="info") else "n/a"

        jobs.append({
            "Title": title,
            "Company": company,
            "Location": location,
            "Salary": salary,
            "Freshness": freshness,
            "Link": full_link,
            "Offer_ID": offer_id,
            "Description": "",
            "Skills": "",
            "Worktype": "",
            "Seniority": "",
            "EmploymentType": "",
            "Status": ""
        })

    return jobs, matched_count, skipped_count

def build_search_url(term, sort_by, count_days=None):
    params = {"search_anywhere": term, "sort_by": sort_by}
    if count_days is not None and count_days > 0:
        params["count_days"] = count_days
    return BASE_URL + "?" + urlencode(params)

def main():
    output_path = Path(OUTPUT_FILE)
    existing_offer_ids = set()

    # Decide count_days logic
    if output_path.is_file() and output_path.stat().st_size > 0:
        if FORCE_LAST_DAY_WHEN_CSV_EXISTS:
            effective_count_days = 2
            print(f"CSV exists → forcing count_days=1 (last 24h)")
        else:
            effective_count_days = None
            print("CSV exists but FORCE_LAST_DAY disabled → full scan")
    else:
        effective_count_days = None
        print("First run (no CSV) → full scan")

    # Load existing IDs (for deduplication safety)
    if output_path.is_file():
        with output_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                oid = row.get("Offer_ID", "").strip()
                if oid:
                    existing_offer_ids.add(oid)
        print(f"Loaded {len(existing_offer_ids):,} existing offer IDs")

    all_new_jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 1024},
            locale="sk-SK",
            timezone_id="Europe/Bratislava",
        )
        page = context.new_page()

        for term in SEARCH_TERMS:
            term_lower = term.lower()
            print(f"\n{'─'*65}\nSearching: {term}\n{'─'*65}")

            search_url = build_search_url(term, SORT_BY, effective_count_days)

            try:
                page.goto(search_url, wait_until="networkidle", timeout=TIMEOUT)
                current_url = page.url
            except Exception as e:
                print(f"Failed to load search page: {e}")
                continue

            pg = 1
            while True:
                url = current_url if pg == 1 else f"{current_url}&page_num={pg}"
                try:
                    html = load_page(page, url, pg, term)
                    page_jobs, matched, skipped = parse_jobs(
                        html, BASE_URL, term_lower, existing_offer_ids
                    )
                    print(f"  Page {pg:3} | new: {len(page_jobs):3} | matched: {matched:3} | skipped: {skipped:3}")

                    all_new_jobs.extend(page_jobs)
                    existing_offer_ids.update(j["Offer_ID"] for j in page_jobs)

                    if matched == 0 and pg > 1:
                        print("  No more matches → stopping this term")
                        break

                except Exception as e:
                    print(f"  Page {pg} failed: {e}")
                    break

                pg += 1
                time.sleep(random.uniform(MIN_PAGE_DELAY, MAX_PAGE_DELAY))

        browser.close()

    # ── Save ───────────────────────────────────────
    if all_new_jobs:
        fieldnames = [
            "Title", "Company", "Location", "Salary", "Freshness",
            "Link", "Offer_ID",
            "Description", "Skills", "Worktype", "Seniority",
            "EmploymentType", "Status"
        ]

        exists = output_path.is_file()
        mode = "a" if exists else "w"

        with output_path.open(mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=fieldnames,
                quoting=csv.QUOTE_MINIMAL,
                quotechar='"',
                escapechar='\\'
            )
            if not exists:
                writer.writeheader()
            for job in all_new_jobs:
                row = {k: job.get(k, "") for k in fieldnames}
                writer.writerow(row)

        print(f"\nSuccess. Added {len(all_new_jobs)} new jobs.")
        print(f"Total known unique offers now: {len(existing_offer_ids)}")
        print(f"Saved to: {output_path.resolve()}\n")
    else:
        print("\nNo new jobs found in this run.\n")

if __name__ == "__main__":
    main()

import csv
import time
import random
import re
from urllib.parse import urljoin, urlencode
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
from pathlib import Path

# ────────────────────────────────────────────────
# CONFIG – tune here
# ────────────────────────────────────────────────
BASE_URL = "https://www.profesia.cz/prace/"
SEARCH_TERMS = [
    "developer",
    "programator",
    "inzinýr",
    "engineer",
    "vývojář",
    "javascript",
    "frontend",
    "fullstack",
    "react",

]
SORT_BY = "relevance"          # "relevance", "plat_sestupne", "datum_nahoru"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
OUTPUT_FILE = "jobs.csv"

# Speed / safety
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
@retry(stop=stop_after_attempt(RETRY_COUNT),
       wait=wait_exponential(multiplier=1.2, min=3, max=25),
       retry=retry_if_exception_type(PlaywrightTimeoutError),
       reraise=True)
def load_page(page, url, pg_num, term):
    print(f"[{term}] Page {pg_num}: {url}")
    resp = page.goto(url, wait_until="networkidle", timeout=TIMEOUT)
    if resp is None or resp.status >= 400:
        raise RuntimeError(f"Bad status: {resp.status if resp else 'no response'}")
    page.wait_for_timeout(random.randint(GOTO_EXTRA_WAIT_MS, GOTO_EXTRA_WAIT_MS + 1800))
    return page.content()

# ────────────────────────────────────────────────
def parse_jobs(html, base_url, search_term_lower, existing_offer_ids):
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_ids = set()
    matched_count = 0
    skipped_count = 0

    # Flexible container search (CZ layout varies)
    container = (
        soup.find("ul", class_="list") or
        soup.find("div", class_=re.compile(r"(offer|job|result|list|items)")) or
        soup.find("div", class_=re.compile(r"results|search|offer")) or
        soup.select_one("main, [role=main], .content") or
        soup.body
    )

    if not container:
        print(" → No main results container found")
        return jobs, 0, 0

    # Broader candidate selectors
    candidates = container.select(
        'li[class*="row"], div[class*="offer"], div[class*="job"], div[class*="item"], '
        'div[class*="card"], article, a[href*="/prace/"]'
    )

    for el in candidates:
        # Find link
        a = el.find("a", href=re.compile(r"/prace/")) or (el if el.name == "a" else None)
        if not a:
            continue

        href = a.get("href", "")
        if "/prace/" not in href or len(href) < 15:
            continue

        full_link = urljoin(base_url, href)

        # Offer ID – prefer number from URL slug
        offer_id_match = re.search(r"/(\d+)(?:/|\?|$)", href)
        offer_id = offer_id_match.group(1) if offer_id_match else a.get("id", "").replace("offer", "")
        if not offer_id:
            offer_id = str(hash(href) % 10**10)  # fallback
        if offer_id in seen_ids or offer_id in existing_offer_ids:
            skipped_count += 1
            continue
        seen_ids.add(offer_id)

        # Title
        title_el = a.find(["span", "h2", "h3"], class_=re.compile(r"(title|nazev|position)")) or a
        title = title_el.get_text(strip=True).lower() if title_el else "n/a"

        if search_term_lower not in title:
            continue

        matched_count += 1

        # Company
        company = "n/a"
        co_el = el.find(string=re.compile(r"(?i)(s\.r\.o\.|a\.s\.|spol\. s r.o.|v.o.s.)")) or \
                el.find(["span", "div"], class_=re.compile(r"(employer|firma|company|zaměstnavatel)"))
        if co_el:
            company = (co_el.get_text(strip=True).lower() if hasattr(co_el, 'get_text') else co_el.strip().lower())

        # Location
        location = "n/a"
        loc_el = el.find(string=re.compile(r"(?i)(praha|brno|ostrava|plzeň|olomouc|liberec|pardubice|hradec|ústí|karlovy|zlín|jihlava|remote|home office)"))
        if loc_el:
            location = loc_el.strip().lower()

        # Salary
        salary = "n/a"
        sal_txt = el.get_text(" ", strip=True).lower()
        if any(c.isdigit() for c in sal_txt) and any(w in sal_txt for w in ["kč", "mzda", "plat", "od ", "až "]):
            salary = sal_txt.split("kč")[0].rsplit(" ", 2)[-2:]   # rough last number phrase
            salary = " ".join(salary).strip() + " kč"

        # Freshness
        freshness = "n/a"
        fresh_txt = el.find(string=re.compile(r"(?i)(před|dnes|včera|hod|min|den|týden|měsíc)"))
        if fresh_txt:
            freshness = fresh_txt.strip().lower()

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

# ────────────────────────────────────────────────
def build_search_url(term, sort_by):
    params = {"search_anywhere": term, "sort_by": sort_by}
    return BASE_URL + "?" + urlencode(params)

# ────────────────────────────────────────────────
def main():
    all_new_jobs = []
    existing_offer_ids = set()
    output_path = Path(OUTPUT_FILE)

    is_first_run = not output_path.is_file()

    if is_first_run:
        print(f"\n=== FIRST RUN ===\nNo {OUTPUT_FILE} → full scan")
    else:
        print(f" → Incremental scan (existing jobs will be skipped by Offer_ID)")

    if output_path.is_file():
        with output_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                oid = row.get("Offer_ID", "").strip()
                if oid:
                    existing_offer_ids.add(oid)
        print(f" Loaded {len(existing_offer_ids):,} existing jobs (will skip duplicates)")
        print("")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 1024},
            locale="cs-CZ",
            timezone_id="Europe/Prague",
        )
        page = context.new_page()

        for term in SEARCH_TERMS:
            term_lower = term.lower()
            print(f"{'─'*60}\nTerm: {term}\n{'─'*60}")

            search_url = build_search_url(term, SORT_BY)

            try:
                page.goto(search_url, wait_until="networkidle", timeout=TIMEOUT)
                current_url = page.url
            except Exception as e:
                print(f" Failed to load search: {e}")
                continue

            pg = 1
            while True:
                url = current_url if pg == 1 else f"{current_url}&page_num={pg}" if "?" in current_url else f"{current_url}?page_num={pg}"
                try:
                    html = load_page(page, url, pg, term)
                    page_jobs, matched_count, skipped_count = parse_jobs(
                        html, BASE_URL, term_lower, existing_offer_ids
                    )
                    print(f" Page {pg:3} → {len(page_jobs)} new | {matched_count} matched | {skipped_count} skipped")
                    all_new_jobs.extend(page_jobs)
                    existing_offer_ids.update(j["Offer_ID"] for j in page_jobs)

                    if matched_count == 0 and pg > 1:
                        print(f" No more matches on page {pg} → stopping term")
                        break
                except Exception as e:
                    print(f" Page {pg} failed: {e}")
                    break

                pg += 1
                time.sleep(random.uniform(MIN_PAGE_DELAY, MAX_PAGE_DELAY))

        browser.close()

    # ── Save (append if exists) ────────────────────────────────────
    if all_new_jobs:
        fieldnames = [
            "Title", "Company", "Location", "Salary", "Freshness",
            "Link", "Offer_ID",
            "Description", "Skills", "Worktype", "Seniority", "EmploymentType",
            "Status"
        ]

        exists = output_path.is_file()
        mode = "a" if exists else "w"

        with output_path.open(mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=fieldnames,
                quoting=csv.QUOTE_MINIMAL,
                quotechar='"',
                escapechar='\\'
            )

            if not exists:
                writer.writeheader()

            for job in all_new_jobs:
                row = {k: job.get(k, "") for k in fieldnames}
                writer.writerow(row)

        print(f"\nFinished.")
        print(f" Added {len(all_new_jobs)} new jobs")
        print(f" Total unique jobs now: {len(existing_offer_ids)}")
        print(f" File: {output_path.resolve()}")
    else:
        print("\nNo new jobs found in this run.")


if __name__ == "__main__":
    main()
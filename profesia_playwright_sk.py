import csv
import time
import random
import re
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup

BASE_URL = "https://www.profesia.sk/praca"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

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

    # Wait for job list or any job link
    try:
        page.wait_for_selector("ul.list li.list-row, a[href*='/praca/']", timeout=35000)
        print("   → Job listings detected")
    except PlaywrightTimeoutError:
        print("   → No jobs found after wait – possible block / empty page / JS issue")

    page.wait_for_timeout(random.randint(3000, 7000))  # mimic human
    html = page.content()

    debug_file = f"debug_page_{pg_num}.html"
    with open(debug_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"   → Debug saved → {debug_file} (open in browser to inspect)")

    return html


def parse_jobs(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    seen_ids = set()

    # Main list
    list_container = soup.find("ul", class_="list")
    if not list_container:
        print("   → No <ul class='list'> found – structure changed?")
        return jobs

    for li in list_container.find_all("li", class_="list-row"):
        # Skip promo/ad tiles
        if "promo-tile" in li.get("class", []):
            continue

        # Title link – most reliable anchor
        title_a = li.find("h2").find("a") if li.find("h2") else None
        if not title_a:
            continue

        offer_id = title_a.get("id", "").replace("offer", "")
        if not offer_id or offer_id in seen_ids:
            continue
        seen_ids.add(offer_id)

        href = title_a.get("href")
        if not href or "/praca/" not in href:
            continue
        full_link = urljoin(base_url, href)

        title_span = title_a.find("span", class_="title")
        title = title_span.get_text(strip=True) if title_span else title_a.get_text(strip=True)

        employer_span = li.find("span", class_="employer")
        company = employer_span.get_text(strip=True) if employer_span else "N/A"

        loc_span = li.find("span", class_="job-location")
        location = loc_span.get_text(strip=True) if loc_span else "N/A"
        loc_title = loc_span.get("title", "").strip() if loc_span else ""
        if loc_title and loc_title != location:
            location = f"{location} ({loc_title})"

        # Salary label
        salary = "N/A"
        salary_label = li.find("span", class_="label", string=re.compile(r"EUR|mesiac|hod\."))
        if salary_label:
            salary = salary_label.get_text(strip=True).replace("\xa0", " ")

        # Freshness
        freshness_span = li.find("span", class_="info")
        freshness = freshness_span.get_text(strip=True) if freshness_span else "N/A"

        jobs.append({
            "Title": title,
            "Company": company,
            "Location": location,
            "Salary": salary,
            "Freshness": freshness,
            "Link": full_link,
            "Offer_ID": offer_id,
        })

    print(f"   → Extracted {len(jobs)} valid jobs")
    return jobs


def main(max_pages=5, output_file="profesia_jobs_2026.csv"):
    all_jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 1024},
            locale="sk-SK",
            timezone_id="Europe/Bratislava",
        )
        page = context.new_page()

        for pg in range(1, max_pages + 1):
            url = f"{BASE_URL}?page_num={pg}"

            try:
                html = load_page(page, url, pg)
                page_jobs = parse_jobs(html, BASE_URL)
                print(f"   → Page {pg} → {len(page_jobs)} jobs")
                all_jobs.extend(page_jobs)
            except Exception as e:
                print(f"   → FAILED page {pg}: {e}")
                break

            time.sleep(random.uniform(12, 25))  # polite delay

        browser.close()

    if all_jobs:
        keys = ["Title", "Company", "Location", "Salary", "Freshness", "Link", "Offer_ID"]
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_jobs)
        print(f"\nDone! Saved {len(all_jobs)} jobs → {output_file}")
    else:
        print("\nNo jobs scraped. Check debug_page_*.html files → search for job titles.")
        print("If empty → likely Cloudflare / bot block → add residential proxy + playwright-stealth.")


if __name__ == "__main__":
    # pip install playwright tenacity beautifulsoup4 lxml
    # playwright install
    main(max_pages=4)  # increase slowly; use proxies for >10 pages
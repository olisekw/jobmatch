"""profesia.sk adapter — ported from the original src/sk.py + src/fill.py."""

import re
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

import config
from .base import JobSource, fold

BASE_URL = "https://www.profesia.sk/praca/"


def canonical_link(link):
    parts = urlsplit(link)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def build_search_url(term, count_days=None):
    params = {"search_anywhere": term, "sort_by": "relevance"}
    if count_days:
        params["count_days"] = count_days
    return BASE_URL + "?" + urlencode(params)


def parse_jobs(html, term_lower, known_ids):
    """Parse one result page. Returns (new job stubs, matched count on page)."""
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    matched = 0

    list_container = soup.find("ul", class_="list")
    if not list_container:
        return jobs, 0

    seen = set()
    for li in list_container.find_all("li", class_="list-row"):
        if "promo-tile" in li.get("class", []):
            continue

        title_a = li.find("h2").find("a") if li.find("h2") else None
        if not title_a:
            continue

        offer_id = title_a.get("id", "").replace("offer", "")
        if not offer_id or offer_id in seen:
            continue
        seen.add(offer_id)

        href = title_a.get("href", "")
        if not href or "/praca/" not in href:
            continue

        title_span = title_a.find("span", class_="title")
        title = (title_span.get_text(strip=True).lower()
                 if title_span else title_a.get_text(strip=True).lower())
        if fold(term_lower) not in fold(title):
            continue
        matched += 1

        if offer_id in known_ids:
            continue

        company = li.find("span", class_="employer")
        company = company.get_text(strip=True).lower() if company else None

        loc_span = li.find("span", class_="job-location")
        location = loc_span.get_text(strip=True).lower() if loc_span else None
        loc_title = loc_span.get("title", "").strip().lower() if loc_span else ""
        if location and loc_title and loc_title != location:
            location = f"{location} ({loc_title})"

        salary = None
        sal_span = li.find("span", class_=re.compile(r"label.*(?:green|salary|money|plat|mzda)"))
        if sal_span:
            text = sal_span.get_text(strip=True).replace("\xa0", " ").strip().lower()
            if any(c.isdigit() for c in text):
                salary = text

        info = li.find("span", class_="info")
        freshness = info.get_text(strip=True).lower() if info else None

        jobs.append({
            "source_id": offer_id,
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "freshness": freshness,
            "link": canonical_link(urljoin(BASE_URL, href)),
        })

    return jobs, matched


class ProfesiaSource(JobSource):
    name = "profesia"
    label = "Profesia.sk"
    needs_browser = True

    def search(self, page, terms, days, known_ids, ctx):
        stubs = []
        for i, term in enumerate(terms, 1):
            if ctx.stopped():
                break
            ctx.progress(f"{self.label}: searching '{term}' ({i}/{len(terms)})")
            stubs.extend(self._search_term(page, term, days, known_ids, ctx))
        return stubs

    def _search_term(self, page, term, days, known_ids, ctx):
        term_lower = term.lower()
        stubs = []

        search_url = build_search_url(term, days)
        page.goto(search_url, wait_until="networkidle", timeout=config.TIMEOUT_GOTO)
        current_url = page.url

        pg = 1
        while not ctx.stopped():
            url = current_url if pg == 1 else f"{current_url}&page_num={pg}"
            ctx.progress(f"{self.label}: '{term}' page {pg}")
            try:
                page.goto(url, wait_until="networkidle", timeout=config.TIMEOUT_GOTO)
                page.wait_for_timeout(1500)
                html = page.content()
            except PlaywrightTimeoutError:
                break

            page_jobs, matched = parse_jobs(html, term_lower, known_ids)
            stubs.extend(page_jobs)
            known_ids.update(j["source_id"] for j in page_jobs)

            if matched == 0 and pg > 1:
                break

            pg += 1
            if not ctx.sleep(config.MIN_PAGE_DELAY, config.MAX_PAGE_DELAY):
                break

        return stubs

    def fetch_detail(self, page, url):
        page.goto(url, wait_until="networkidle", timeout=config.TIMEOUT_GOTO)
        page.wait_for_timeout(1500)
        try:
            page.wait_for_selector(".card.card-content", timeout=config.TIMEOUT_CARD)
        except PlaywrightTimeoutError:
            return ""
        cards = page.query_selector_all(".card.card-content")
        if not cards:
            return ""
        return " ".join(cards[0].inner_text().split()).strip()

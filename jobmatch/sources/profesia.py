"""profesia.sk adapter — ported from the original src/sk.py + src/fill.py.

The one board that needs a real browser, which makes it the heaviest dependency
here and the one most likely to break quietly: a markup change costs nothing at
runtime, it just parses zero rows for ever. So every step reports what it saw —
`ctx.seen()` per page, `ctx.warn()` for a page that never loaded — and the scan
tells the dashboard when a whole source came back empty.
"""

import re
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

import config

from .base import JobSource, fold

BASE_URL = "https://www.profesia.sk/praca/"

# A search that never stops paginating is the failure mode of trusting a site's
# own "no more results" signal. Kariéra caps the same way; 40 pages × 20 offers
# is far past anything a term should legitimately return within the scan window.
MAX_PAGES = 40


def canonical_link(link):
    parts = urlsplit(link)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def build_search_url(term, count_days=None):
    params = {"search_anywhere": term, "sort_by": "relevance"}
    if count_days:
        params["count_days"] = count_days
    return BASE_URL + "?" + urlencode(params)


def parse_jobs(html, term_lower, known_ids):
    """Parse one result page.

    Returns (new job stubs, matched count on page, listings on page). The third
    number is the honest one: stubs and matches are both zero on a page full of
    offers we already know, while `listed` is zero only when nothing on the page
    parsed as an offer at all — which is the shape a redesign arrives in.
    """
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    matched = 0
    listed = 0

    list_container = soup.find("ul", class_="list")
    if not list_container:
        return jobs, 0, 0

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
        # Counted here rather than per <li>: a redesign that leaves the rows in
        # place but moves the title or the link is still an offer we cannot
        # read, and it should raise the alarm rather than pass for a listing.
        listed += 1

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

    return jobs, matched, listed


class ProfesiaSource(JobSource):
    name = "profesia"
    label = "Profesia.sk"
    needs_browser = True

    def search(self, page, terms, days, known_ids, ctx):
        stubs = []
        for i, term in enumerate(terms, 1):
            if ctx.stopped():
                break
            ctx.progress(f"Searching {self.label} for “{term}” ({i} of {len(terms)})")
            stubs.extend(self._search_term(page, term, days, known_ids, ctx))
        return stubs

    def _search_term(self, page, term, days, known_ids, ctx):
        term_lower = term.lower()
        stubs = []

        # The URL profesia redirects the search to; page 2 onwards hangs
        # `&page_num=` off it. Unknown until the first page has been fetched,
        # which is why the loop asks for `build_search_url` only on page 1 —
        # fetching it once up front and again as page 1 was two hits on the
        # board for one page of results, with no politeness delay between them.
        base_url = None

        for pg in range(1, MAX_PAGES + 1):
            if ctx.stopped():
                break
            url = build_search_url(term, days) if base_url is None else f"{base_url}&page_num={pg}"
            ctx.progress(f"Searching {self.label} for “{term}” — page {pg}")
            html = self._load(page, url, ctx)
            if html is None:
                ctx.warn(f"“{term}” page {pg} did not load")
                break
            if base_url is None:
                base_url = page.url

            page_jobs, matched, listed = parse_jobs(html, term_lower, known_ids)
            ctx.seen(listed)
            stubs.extend(page_jobs)
            known_ids.update(j["source_id"] for j in page_jobs)

            if listed == 0 or (matched == 0 and pg > 1):
                break

            if not ctx.sleep(config.MIN_PAGE_DELAY, config.MAX_PAGE_DELAY):
                break

        return stubs

    def _load(self, page, url, ctx):
        """Fetch one result page, retrying a timeout. None if it never loaded.

        A single slow response used to end the search for that term silently,
        which is indistinguishable from the term having no results — so it
        retries once, and the caller reports the give-up rather than shrugging.
        """
        for attempt in range(config.MAX_RETRIES):
            try:
                page.goto(url, wait_until="networkidle", timeout=config.TIMEOUT_GOTO)
                page.wait_for_timeout(1500)
                return page.content()
            except PlaywrightTimeoutError:
                if attempt + 1 >= config.MAX_RETRIES:
                    return None
                if not ctx.sleep(config.MIN_PAGE_DELAY, config.MAX_PAGE_DELAY):
                    return None
        return None

    def fetch_detail(self, page, url):
        """The description off one offer page, or '' when it is not there.

        An empty answer is not silence: the enrich phase counts it as a read
        that failed, so a `.card.card-content` that stops existing surfaces as a
        failure count on the scan rather than as a pool of descriptionless jobs
        that every later scan quietly retries.
        """
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

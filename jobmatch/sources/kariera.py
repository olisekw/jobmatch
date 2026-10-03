"""kariera.zoznam.sk adapter.

Server-rendered listing pages fetched over plain HTTP (no Playwright needed).
Search: /pracovne-ponuky?q=<term>&filter[age]=<days>&od=<offset>, 30 per page,
cards are div.offer with h2.offer-title / .offer-employer / .offer-locality.
Detail: description lives in div.detail.
"""

import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .. import dates
from .base import JobSource, fold, http_get

BASE_URL = "https://kariera.zoznam.sk/"
PER_PAGE = 30
MAX_PAGES = 40

# kariera only accepts fixed lookback windows (days)
AGE_STEPS = (1, 2, 7, 31, 183, 365)


def _age_for(days):
    if not days:
        return None
    for step in AGE_STEPS:
        if days <= step:
            return step
    return 365


def _search_url(term, days, offset):
    url = f"{BASE_URL}pracovne-ponuky?q={quote(term)}"
    age = _age_for(days)
    if age:
        url += f"&filter%5Bage%5D={age}"
    if offset:
        url += f"&od={offset}"
    return url


def parse_offers(html, term_lower, known_ids):
    """→ (stubs, matched, listed, rows).

    The last two are different questions and a single number answered neither
    honestly. `listed` is what the silent-board alarm judges this adapter on:
    offers the parser could actually *read* — a card, its title link, and an id
    off the href — because a redesign that leaves the cards in place and moves
    the title is still a page we cannot read, and counting the container would
    report it as life. (Measured against the live board on 2026-09-22: four
    realistic redesigns left a `div.offer` count of six standing while the
    parser produced nothing.) It is the same rule `profesia.parse_jobs` and
    `jobscz.parse_cards` already count by.

    `rows` is the cruder count — every non-promoted card the board served — and
    it is what says whether this was a full page. Pagination has to ask that
    one: a page whose promoted slots the parser skips is still a full page, and
    stopping on it would silently truncate the crawl.
    """
    soup = BeautifulSoup(html, "lxml")
    stubs = []
    matched = 0
    listed = 0
    rows = 0

    for offer in soup.select("div.offer"):
        if "highlight" in offer.get("class", []):
            continue  # promoted banner slot
        rows += 1
        title_a = offer.select_one("h2.offer-title a")
        if not title_a:
            continue
        href = title_a.get("href", "")
        if "redirect.php" in href:
            continue  # promoted listing
        m = re.search(r"pracovna-ponuka/(\d+)/", href)
        if not m:
            continue
        source_id = m.group(1)
        listed += 1

        title = title_a.get_text(strip=True).lower()
        if fold(term_lower) not in fold(title):
            continue
        matched += 1
        if source_id in known_ids:
            continue

        company_el = offer.select_one(".offer-employer")
        location_el = offer.select_one(".offer-locality")
        date_el = offer.select_one(".offer-bottom-right .date")
        salary = None
        for li in offer.select("ul.offer-info li"):
            text = li.get_text(" ", strip=True)
            if "eur" in text.lower() and any(c.isdigit() for c in text):
                salary = text.lower()
                break

        freshness = date_el.get_text(strip=True) if date_el else None
        stubs.append({
            "source_id": source_id,
            "title": title,
            "company": company_el.get_text(strip=True).lower() if company_el else None,
            "location": location_el.get_text(strip=True).lower() if location_el else None,
            "salary": salary,
            "freshness": freshness,
            "posted_at": dates.parse_posted(freshness),
            "link": urljoin(BASE_URL, href),
        })

    return stubs, matched, listed, rows


class KarieraSource(JobSource):
    name = "kariera"
    label = "Kariéra.sk"

    def search(self, page, terms, days, known_ids, ctx):
        stubs = []
        for i, term in enumerate(terms, 1):
            if ctx.stopped():
                break
            ctx.progress(f"Searching {self.label} for “{term}” ({i} of {len(terms)})")
            stubs.extend(self._search_term(term, days, known_ids, ctx))
        return stubs

    def _search_term(self, term, days, known_ids, ctx):
        term_lower = term.lower()
        stubs = []

        for pg in range(MAX_PAGES):
            if ctx.stopped():
                break
            ctx.progress(f"Searching {self.label} for “{term}” — page {pg + 1}")
            html = http_get(_search_url(term, days, pg * PER_PAGE))
            page_stubs, matched, listed, rows = parse_offers(html, term_lower, known_ids)
            stubs.extend(page_stubs)
            known_ids.update(s["source_id"] for s in page_stubs)

            # What the board showed us *and this parser could read*, whether or
            # not any of it was new — the number the orchestrator judges "this
            # adapter still works" on. Pagination asks `rows` instead: "was
            # this a full page" and "did we understand it" are not one question.
            ctx.seen(listed)
            if rows < PER_PAGE or (matched == 0 and pg > 0):
                break
            if not ctx.sleep(2.0, 5.0):
                break

        return stubs

    def fetch_detail(self, page, url):
        html = http_get(url)
        soup = BeautifulSoup(html, "lxml")
        # kariera serves two detail templates depending on the offer type
        detail = soup.select_one("div.detail") or soup.select_one("div.offer-detail-content")
        if not detail:
            return ""
        return " ".join(detail.get_text(" ", strip=True).split())

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
    soup = BeautifulSoup(html, "lxml")
    stubs = []
    matched = 0

    for offer in soup.select("div.offer"):
        if "highlight" in offer.get("class", []):
            continue  # promoted banner slot
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

    return stubs, matched


class KarieraSource(JobSource):
    name = "kariera"
    label = "Kariéra.sk"

    def search(self, page, terms, days, known_ids, ctx):
        stubs = []
        for i, term in enumerate(terms, 1):
            if ctx.stopped():
                break
            ctx.progress(f"{self.label}: searching '{term}' ({i}/{len(terms)})")
            stubs.extend(self._search_term(term, days, known_ids, ctx))
        return stubs

    def _search_term(self, term, days, known_ids, ctx):
        term_lower = term.lower()
        stubs = []

        for pg in range(MAX_PAGES):
            if ctx.stopped():
                break
            ctx.progress(f"{self.label}: '{term}' page {pg + 1}")
            html = http_get(_search_url(term, days, pg * PER_PAGE))
            page_stubs, matched = parse_offers(html, term_lower, known_ids)
            stubs.extend(page_stubs)
            known_ids.update(s["source_id"] for s in page_stubs)

            # last page reached: fewer than a full page of offers listed
            soup = BeautifulSoup(html, "lxml")
            total_offers = len(soup.select("div.offer")) - len(soup.select("div.offer.highlight"))
            if total_offers < PER_PAGE or (matched == 0 and pg > 0):
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

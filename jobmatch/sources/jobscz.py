"""jobs.cz adapter — the Czech board, server-rendered HTML over plain HTTP.

Phase 8's "more EU-remote boards" bullet named three; this is the one that
survived contact with them. `nofluffjobs` serves its listings from an API that
its own robots.txt disallows (`/api/`, and `/posting/` for the detail pages),
behind a page that renders nothing without JavaScript — so the only polite way
in is a door the site has closed. `startup.jobs` answers 403 to everything
except robots.txt, its feed included. Neither is a scraper we should write;
both are recorded in ROADMAP.md rather than half-built here.

Search: /prace/?q[0]=<term>&date=<step>&page=<n>, 30 cards per page,
`article.SearchResultCard` — plain HTTP, and it never touches the browser.

**Detail is two boards wearing one URL.** Every card links to
`www.jobs.cz/rpd/<id>/`, and that 302s to one of two very different pages:
jobs.cz's own ad view (`/rpd/`, `/fp/…`), which is server-rendered and read
here with `[data-test=jd-body-richtext]`; or the employer's microsite
(`<company>.jobs.cz/detail-pozice?…`), which is an arbitrary company template
with a JS widget where the ad should be. Measured over 30 live ads across two
terms: **21 hosted, 9 microsite** — so plain HTTP alone reads about seven ads
in ten, and the other three land with no description, unscored, and re-fetched
by every later scan forever (`_enrich_phase` selects on an empty description,
so a row it can never fill is a politeness delay paid every time).

Nothing is missing from the microsite's HTML that a better selector would find:
the body is fetched client-side from a GraphQL endpoint the page's widget calls,
and that endpoint is the same kind of door `nofluffjobs` was rejected for below.
So the browser renders it instead, under `#capybara-position-detail` — confirmed
on three unrelated employers, and absent from jobs.cz's own view, so the two
pages tell themselves apart by which selector answers rather than by parsing
the URL, which is a redirect target we do not control.

Hence `needs_browser = True`, which is a claim about the *detail* pages only:
`search` uses `http_get` throughout and would work with no browser at all. It is
declared anyway because "sometimes" is worse than "yes" — without it this
adapter would read those three ads in ten only when profesia happened to be
enabled too (the orchestrator hands the shared page to every source once any
source has asked for one), and whether a Czech job is scored must not depend on
whether an unrelated Slovak board is switched on.

Two things about this board had to be measured rather than assumed, and both
are the reason the roadmap says an unconfirmed parameter is worse than none:

- **It ignores what it does not understand.** `&zzzbogus=1` returns the same
  282 results as no parameter at all, character for character — the Remotive
  failure mode, where a guessed filter looks like it works and silently does
  nothing. So every parameter below was confirmed by watching the result count
  move, against a board whose answers are otherwise deterministic (the same URL
  twice gives the same ads in the same order).
- **`date` takes three values and falls back to *unfiltered*.** `24h`, `3d` and
  `7d` narrowed 282 → 23, 74 and 139; `1d`, `2d`, `4d`, `14d`, `30d`, `1m`,
  `1w` and a nonsense `99z` all returned the full 282. A window this board does
  not know is not an error here, it is the whole board — so `_date_step` only
  ever sends one of the three it was shown to honour, and asks for everything
  when the user's window is wider than a week.

`ctx.regions` is not sent: there is no confirmed geography parameter, and the
board is Czech in the first place, so there is no continent being fetched and
thrown away. Placement comes from `places`, with `jobscz` defaulting to CZ.
"""

import re
from urllib.parse import quote

from bs4 import BeautifulSoup

import config

from .. import dates
from .base import JobSource, http_get

BASE_URL = "https://www.jobs.cz/prace/"
PER_PAGE = 30
MAX_PAGES = 20

# The only three windows the board honours; anything else is the whole board.
DATE_STEPS = ((1, "24h"), (3, "3d"), (7, "7d"))

# The board states remote and hybrid and says nothing at all about on-site, so
# an absent tag is silence rather than a fact — which is why `worktype` here
# can come back None and let `extract` read the description instead.
_REMOTE_TAG = re.compile(r"převážně z domova|prevazne z domova|plně z domova|plne z domova")
_HYBRID_TAG = re.compile(r"občasné práce z domova|obcasne prace z domova|částečně z domova")

# "Přidáno …" / "Aktualizováno …" is when the ad appeared; "Končí za 3 dny" is
# when it expires. Both sit in the same element, and reading the second as the
# first would date a job by its deadline.
_POSTED_STATUS = re.compile(r"přidáno|pridano|aktualizováno|aktualizovano|\d")
_EXPIRY_STATUS = re.compile(r"končí|konci")

_CURRENCY_TAG = re.compile(r"kč|czk|eur|€")

# jobs.cz's own ad view, server-rendered; and the employer microsites' widget,
# which only exists once JavaScript has run. A page answers to one or the other,
# never both, which is how the two are told apart.
#
# The microsites come in (at least) two templates, and the id each one hangs the
# ad on differs — `#capybara-position-detail` on one, `#vacancy-detail` on the
# other — which cost three of thirty ads on the first full live scan. `.cp-detail`
# is the class both build on: measured identical to whichever id applies, across
# six unrelated employers spanning both templates.
HOSTED_SELECTORS = ("[data-test=jd-body-richtext]", ".RichContent")
WIDGET_SELECTOR = ".cp-detail"

# The widget mounts its container before it has the ad — an empty shell measured
# at 11 characters against real bodies of 2 800–6 000. The floor is what tells
# "still loading" from "loaded", and is deliberately far below any real posting.
MIN_BODY_CHARS = 200
WIDGET_POLLS = 4
WIDGET_POLL_MS = 2000


def _hosted_body(html):
    """The description off jobs.cz's own ad view, or '' if this is not one."""
    soup = BeautifulSoup(html, "lxml")
    for selector in HOSTED_SELECTORS:
        body = soup.select_one(selector)
        if body:
            return " ".join(body.get_text(" ", strip=True).split())
    return ""


def _date_step(days):
    """The board's own window token for `days`, or None to ask for everything."""
    if not days:
        return None
    for limit, token in DATE_STEPS:
        if days <= limit:
            return token
    return None


def _search_url(term, days, page):
    url = f"{BASE_URL}?q%5B0%5D={quote(term)}"
    step = _date_step(days)
    if step:
        url += f"&date={step}"
    if page > 1:
        url += f"&page={page}"
    return url


def _text(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else None


def _worktype(card_text):
    if _REMOTE_TAG.search(card_text):
        return "remote"
    if _HYBRID_TAG.search(card_text):
        return "hybrid"
    return None


def _freshness(card):
    status = _text(card.select_one(".SearchResultCard__status"))
    if not status:
        return None
    lowered = status.lower()
    if _EXPIRY_STATUS.search(lowered):
        return None
    return status if _POSTED_STATUS.search(lowered) else None


def parse_cards(html, known_ids):
    """→ (stubs, listings_seen). `listings_seen` counts every ad on the page.

    Separate from the stub count on purpose: a page of ads we already have and
    a page this parser can no longer read both yield no stubs, and only the
    second one is a broken adapter. See `ScanContext.seen`.
    """
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("article.SearchResultCard")
    stubs = []
    seen = 0

    for card in cards:
        link = card.select_one("a.SearchResultCard__titleLink")
        if not link:
            continue    # a card whose title link moved is unread, not a listing
        source_id = link.get("data-jobad-id")
        href = link.get("href")
        if not source_id or not href:
            continue
        seen += 1
        if source_id in known_ids:
            continue

        title = _text(link)
        if not title:
            continue

        location = _text(card.select_one("[data-test=serp-locality]"))
        if location:
            # "Brno – Starý Lískovec + 1 další lokalita" — the extra localities
            # are a count, not a place, and `places` should not read them.
            location = re.sub(r"\s*\+\s*\d+\s+dal[šs].*$", "", location).strip()

        # The footer lists company, locality and an Atmoskop rating; only the
        # first has no data-test of its own, which is what identifies it.
        company = None
        for item in card.select("footer li"):
            if item.select_one("[data-test]") or item.get("data-test"):
                continue
            company = _text(item)
            break

        salary = None
        for tag in card.select(".Tag"):
            text = _text(tag) or ""
            if any(ch.isdigit() for ch in text) and _CURRENCY_TAG.search(text.lower()):
                salary = text.lower()
                break

        freshness = _freshness(card)
        stubs.append({
            "source_id": source_id,
            "title": title.lower(),
            "company": company.lower() if company else None,
            "location": location.lower() if location else None,
            "salary": salary,
            "freshness": freshness,
            "posted_at": dates.parse_posted(freshness),
            "link": href.split("?")[0],
            "worktype": _worktype(card.get_text(" ", strip=True).lower()),
        })

    return stubs, seen


class JobsCzSource(JobSource):
    name = "jobscz"
    label = "Jobs.cz"
    # For the detail pages only — see the module docstring. `search` never uses
    # the page it is handed.
    needs_browser = True
    # `worktype` only. The salary tag carries no period, so it goes through
    # `salary.parse_salary` like every other board's text rather than being
    # declared here as something the board stated.
    provides = frozenset({"worktype"})

    def search(self, page, terms, days, known_ids, ctx):
        stubs = []
        for i, term in enumerate(terms, 1):
            if ctx.stopped():
                break
            ctx.progress(f"Searching {self.label} for “{term}” ({i} of {len(terms)})")
            stubs.extend(self._search_term(term, days, known_ids, ctx))
        return stubs

    def _search_term(self, term, days, known_ids, ctx):
        stubs = []

        for pg in range(1, MAX_PAGES + 1):
            if ctx.stopped():
                break
            ctx.progress(f"Searching {self.label} for “{term}” — page {pg}")
            try:
                html = http_get(_search_url(term, days, pg))
            except Exception as e:
                # A term that 500s is not a term with no jobs, and the two are
                # indistinguishable once this returns.
                ctx.warn(f"“{term}” page {pg}: {e}")
                break

            page_stubs, seen = parse_cards(html, known_ids)
            ctx.seen(seen)
            stubs.extend(page_stubs)
            known_ids.update(s["source_id"] for s in page_stubs)

            if seen < PER_PAGE:
                break   # a short page is the last page
            if not ctx.sleep(config.MIN_PAGE_DELAY, config.MAX_PAGE_DELAY):
                break

        return stubs

    def fetch_detail(self, page, url):
        """The ad body, from whichever of the two pages this link lands on.

        Plain HTTP first, because seven ads in ten are jobs.cz's own view and
        reading them costs one request and no browser. The employer microsites
        are the rest, and no selector reaches their body without JavaScript, so
        they are re-fetched through the page — the *only* reason this adapter
        declares `needs_browser`. An empty answer is not silence: the enrich
        phase counts it as a read that failed, which is what keeps a board that
        redesigned itself from looking like a board with nothing new.
        """
        body = _hosted_body(http_get(url))
        if body:
            return body
        if page is None:
            return ""
        return self._rendered_body(page, url)

    def _rendered_body(self, page, url):
        """The microsite's ad body, once its widget has actually filled in.

        The wait is on the network rather than on the selector because the
        widget mounts `#capybara-position-detail` empty and fills it a moment
        later: waiting for the element alone returned an 11-character skeleton,
        which would have been stored as a successful read of a job that then
        scores on nothing and is never re-enriched. So a body too short to be a
        posting is treated as not-yet-there, and finally as a failed read —
        which costs one more scan, where believing the skeleton costs the job.
        """
        page.goto(url, wait_until="networkidle", timeout=config.TIMEOUT_GOTO)
        for _ in range(WIDGET_POLLS):
            node = page.query_selector(WIDGET_SELECTOR)
            if node:
                text = " ".join(node.inner_text().split()).strip()
                if len(text) >= MIN_BODY_CHARS:
                    return text
            page.wait_for_timeout(WIDGET_POLL_MS)
        return ""

"""JobSource interface.

An adapter turns one job board into two operations:

- search(page, term, days, known_ids, ctx) → list of job stubs:
  dicts with source_id, title, company, location, salary, freshness, link.
  Must skip source_ids already in known_ids, honour ctx.stopped() between
  pages, report progress via ctx.progress(text), and — see ScanContext —
  report every listing the board showed it via ctx.seen(n). It may narrow its
  request to ctx.regions if its board takes a geography; ignoring them is
  always correct, since a wider answer is filtered afterwards anyway.

- fetch_detail(page, url) → full plain-text description ('' if not found).

`page` is a Playwright page owned by the scan orchestrator.
"""

import random
import time
import unicodedata
import urllib.parse
import urllib.request

import config


def fold(text):
    """Lowercase + strip diacritics, for accent-insensitive term matching."""
    normalized = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def http_get(url, timeout=30):
    """Plain-HTTP fetch for boards that serve full server-rendered HTML."""
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def http_post(url, form, timeout=30):
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def match_terms(text, terms):
    """True if any search term occurs in text (accent/case-insensitive)."""
    folded = fold(text)
    return any(fold(t) in folded for t in terms)


def strip_html(html):
    """API boards ship descriptions as HTML — reduce to plain text."""
    if not html:
        return ""
    from bs4 import BeautifulSoup
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    return " ".join(text.split())


def normalize_employment_type(value):
    """Map API job-type strings ('full_time', 'Full-Time', …) to our tokens."""
    v = (value or "").lower().replace("_", " ").replace("-", " ")
    if "intern" in v:
        return "internship"
    if "part" in v:
        return "parttime"
    if "contract" in v or "freelance" in v:
        return "freelance"
    if "full" in v:
        return "fulltime"
    return None


def posted_cutoff(days):
    """ISO date of the oldest allowed posting, or None for no window."""
    import datetime
    if not days:
        return None
    return (datetime.date.today() - datetime.timedelta(days=int(days))).isoformat()


class JobSource:
    name = "base"
    label = "Base"
    needs_browser = False   # True → orchestrator must supply a Playwright page

    # False for boards that ship the description with the listing. Their
    # `fetch_detail` has nothing to fetch, so the enrich phase skips them
    # instead of asking and counting the empty answer as a failed read.
    has_detail_page = True

    # Structured fields this board supplies itself, which therefore beat regex
    # extraction. `_insert_stub` already prefers a present stub value; declaring
    # it here lets `jobmatch.reextract` know which stored values it must leave
    # alone once the two are indistinguishable in the DB.
    provides = frozenset()

    def search(self, page, terms, days, known_ids, ctx):
        """Return job stubs matching any of `terms`, newer than `days`.

        Required stub keys: source_id, title, company, location, salary,
        freshness, link. Optional (API boards that already know them):
        description, worktype, seniority, employment_type, posted_at,
        salary_min, salary_max, salary_currency, salary_period.
        Stubs with a description skip the enrich phase entirely.
        """
        raise NotImplementedError

    def fetch_detail(self, page, url):
        raise NotImplementedError


class ScanContext:
    """Progress, cancellation and reporting hooks handed to adapters — plus
    what this particular crawl is asking for.

    The orchestrator builds one of these per source, so `seen` and `warn` need
    no argument saying who is calling: the callbacks already know. `regions`
    rides here rather than in `search`'s signature for the same reason: it is a
    fact about this run, not a new thing every board has to accept.
    """

    def __init__(self, progress=None, stopped=None, seen=None, warn=None, regions=()):
        self._progress = progress or (lambda text: None)
        self._stopped = stopped or (lambda: False)
        self._seen = seen or (lambda count: None)
        self._warn = warn or (lambda text: None)
        # Where the people this crawl serves can work, as `places` codes. An
        # adapter whose board takes a geography narrows its request with it;
        # every other adapter is right to ignore it. Empty means "we could not
        # narrow" — never "nowhere" — so ignoring it is also the safe default.
        self.regions = frozenset(regions or ())

    def progress(self, text):
        self._progress(text)

    def seen(self, count):
        """Report listings the board actually showed us — *before* filtering.

        This is what separates "nothing new today", the normal outcome of an
        incremental scan, from "this adapter no longer understands the page",
        which otherwise looks identical from the outside: both return no stubs.
        Count every listing parsed off the response, matched or not, known or
        not; the orchestrator raises the alarm when a whole source reports zero.
        """
        self._seen(count)

    def warn(self, text):
        """A problem the adapter survived but the scan should still report."""
        self._warn(text)

    def stopped(self):
        return self._stopped()

    def sleep(self, lo, hi):
        """Politeness delay that stays responsive to cancellation."""
        deadline = time.time() + random.uniform(lo, hi)
        while time.time() < deadline:
            if self._stopped():
                return False
            time.sleep(min(0.5, max(0.0, deadline - time.time())))
        return not self._stopped()

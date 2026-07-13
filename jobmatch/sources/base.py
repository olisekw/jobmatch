"""JobSource interface.

An adapter turns one job board into two operations:

- search(page, term, days, known_ids, ctx) → list of job stubs:
  dicts with source_id, title, company, location, salary, freshness, link.
  Must skip source_ids already in known_ids, honour ctx.stopped() between
  pages, and report progress via ctx.progress(text).

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
    """Progress + cancellation hooks handed to adapters by the orchestrator."""

    def __init__(self, progress=None, stopped=None):
        self._progress = progress or (lambda text: None)
        self._stopped = stopped or (lambda: False)

    def progress(self, text):
        self._progress(text)

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

"""Posted-date parsing: turn board-specific freshness strings into ISO dates."""

import re
from datetime import date, datetime, timedelta

# Slovak relative phrases → age in days (None value = needs the captured number)
_RELATIVE = [
    (r"pred\s+(\d+)\s+min", 0),
    (r"pred\s+minútou", 0),
    (r"pred\s+(\d+)\s+hod", 0),
    (r"pred\s+hodinou", 0),
    (r"\bdnes\b", 0),
    (r"\bvčera\b|\bvcera\b", 1),
    (r"\bpredvčerom\b|\bpredvcerom\b", 2),
    (r"pred\s+(\d+)\s+d[ňn]", "days"),
    (r"pred\s+(\d+)\s+týž|pred\s+(\d+)\s+tyz", "weeks"),
    (r"pred\s+týždňom|pred\s+tyzdnom", 7),
    (r"pred\s+(\d+)\s+mesiac", "months"),
    (r"pred\s+mesiacom", 30),
]


def _reference_date(reference_iso):
    if not reference_iso:
        return date.today()
    try:
        return datetime.fromisoformat(reference_iso.replace(" ", "T")).date()
    except ValueError:
        return date.today()


def parse_posted(freshness, reference_iso=None):
    """Parse a freshness string into an ISO date, or None if unparseable.

    Handles kariera absolute dates (13.07.2026) and profesia Slovak relative
    phrases, interpreted relative to `reference_iso` (the scrape time).
    """
    if not freshness or not isinstance(freshness, str):
        return None
    text = freshness.strip().lower()

    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None

    ref = _reference_date(reference_iso)
    for pattern, value in _RELATIVE:
        m = re.search(pattern, text)
        if not m:
            continue
        if isinstance(value, int):
            return (ref - timedelta(days=value)).isoformat()
        number = int(next(g for g in m.groups() if g))
        if value == "days":
            return (ref - timedelta(days=number)).isoformat()
        if value == "weeks":
            return (ref - timedelta(days=7 * number)).isoformat()
        if value == "months":
            return (ref - timedelta(days=30 * number)).isoformat()
    return None


def days_ago(posted_iso, today=None):
    """Whole days between posted_iso and today, or None."""
    if not posted_iso:
        return None
    try:
        posted = datetime.fromisoformat(posted_iso.replace(" ", "T")).date()
    except ValueError:
        return None
    return max(0, ((today or date.today()) - posted).days)

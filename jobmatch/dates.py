"""Posted-date parsing: turn board-specific freshness strings into ISO dates.

Slovak and Czech share this parser because they share most of the vocabulary —
"dnes" and "včera" are the same word in both — and a second module would only
be a second place for the two to drift apart. What Czech adds is `před` where
Slovak writes `pred`, its own week/month nouns, and jobs.cz's absolute form,
a day and a genitive month name with no year at all ("24. srpna").
"""

import re
from datetime import date, datetime, timedelta

# Slovak/Czech relative phrases → age in days ("days"/"weeks"/"months" = use
# the captured number). `pre[dž]` covers Slovak "pred" and Czech "před" in one
# pattern, since every phrase below is otherwise spelled the same way twice.
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
    # Czech (jobs.cz): "před hodinou", "před 3 dny", "před týdnem", …
    (r"před\s+(\d+)\s+min", 0),
    (r"před\s+minutou", 0),
    (r"před\s+(\d+)\s+hod", 0),
    (r"před\s+hodinou", 0),
    (r"před\s+(\d+)\s+dn[yíi]", "days"),
    (r"před\s+(\d+)\s+týdn|před\s+(\d+)\s+tydn", "weeks"),
    (r"před\s+týdnem|před\s+tydnem", 7),
    (r"před\s+(\d+)\s+měsíc|před\s+(\d+)\s+mesic", "months"),
    (r"před\s+měsícem|před\s+mesicem", 30),
]

# jobs.cz prints a bare day and month for anything older than "včera" — no
# year, because a job board never shows one. The year is therefore inferred,
# and a date that lands in the future belongs to last December, not next.
_CZECH_MONTHS = {
    "ledna": 1, "února": 2, "unora": 2, "března": 3, "brezna": 3, "dubna": 4,
    "května": 5, "kvetna": 5, "června": 6, "cervna": 6, "července": 7,
    "cervence": 7, "srpna": 8, "září": 9, "zari": 9, "října": 10, "rijna": 10,
    "listopadu": 11, "prosince": 12,
}
_CZECH_DATE = re.compile(
    r"\b(\d{1,2})\.\s*(" + "|".join(sorted(_CZECH_MONTHS, key=len, reverse=True)) + r")\b"
)

# jobs.cz prints an ad's *expiry* in the same element as its posting date, and
# the two point opposite ways in time: "Končí za 3 dny" is not three days old,
# it is three days from dying, and "Končí dnes" would otherwise be read as
# posted today by the very word that makes "Přidáno dnes" mean that. A string
# about the end of an ad says nothing about its beginning, so it parses to
# nothing at all.
_EXPIRY = re.compile(r"\bkončí|\bkonci\b|\bvyprší|\bvyprsi")


def _reference_date(reference_iso):
    if not reference_iso:
        return date.today()
    try:
        return datetime.fromisoformat(reference_iso.replace(" ", "T")).date()
    except ValueError:
        return date.today()


def parse_posted(freshness, reference_iso=None):
    """Parse a freshness string into an ISO date, or None if unparseable.

    Handles kariera absolute dates (13.07.2026), jobs.cz's year-less Czech
    ones ("24. srpna"), and profesia/jobs.cz relative phrases, all interpreted
    relative to `reference_iso` (the scrape time).
    """
    if not freshness or not isinstance(freshness, str):
        return None
    text = freshness.strip().lower()
    if _EXPIRY.search(text):
        return None

    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None

    ref = _reference_date(reference_iso)

    m = _CZECH_DATE.search(text)
    if m:
        try:
            parsed = date(ref.year, _CZECH_MONTHS[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
        # No year on the page, so it is this one unless that puts the posting
        # in the future — a board does not advertise jobs it has not listed.
        if parsed > ref:
            try:
                parsed = parsed.replace(year=ref.year - 1)
            except ValueError:
                return None
        return parsed.isoformat()

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

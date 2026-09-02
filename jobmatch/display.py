"""Display helpers: turn stored values into strings a person would write.

Everything here is display-only. Stored values never change shape — `medior`
stays `medior` in the database and in settings; it only *reads* as "Mid-level".
Kept free of DB and Flask imports so the API layer decides what to show and
this module only decides how it reads.

Timestamps are stored as naive UTC ('YYYY-MM-DD HH:MM:SS', see db.NOW), so ages
are computed against `utcnow()` below. Dates read relative — "2 hours ago",
"3 days ago" — which stays correct whatever timezone the reader is in; the
precise value is available separately via `exact_time` for a hover tooltip.
"""

from datetime import datetime, timezone

# ── Labels ───────────────────────────────────────────────────

WORKTYPE = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site"}
SENIORITY = {"junior": "Junior", "medior": "Mid-level", "senior": "Senior"}
EMPLOYMENT_TYPE = {
    "fulltime": "Full-time",
    "parttime": "Part-time",
    "freelance": "Freelance",
    "internship": "Internship",
}
JOB_STATUS = {"new": "New", "applied": "Applied", "declined": "Declined"}
APPLICATION_STATUS = {
    "applied": "Applied",
    "interview": "Interview",
    "offer": "Offer",
    "rejected": "Rejected",
    "withdrawn": "Withdrawn",
    "no_response": "No response",
}
# The tracker's views. A person tracking applications thinks in four states,
# not six: "applied" and "no response" are the same wait, and which of the two
# a row happens to be in is not something anybody filters on. Defined here
# rather than in the page so the tabs, their counts and the status dropdown
# under them cannot drift apart on what a group contains.
APPLICATION_GROUPS = [
    ("all", "Everything", ()),
    ("waiting", "Waiting to hear", ("applied", "no_response")),
    ("interview", "Interviews", ("interview",)),
    ("offer", "Offers", ("offer",)),
    ("rejected", "Rejected", ("rejected",)),
    ("withdrawn", "Withdrawn", ("withdrawn",)),
]

SCAN_STATUS = {
    "queued": "Queued",
    "running": "Running",
    "done": "Finished",
    "failed": "Failed",
    "cancelled": "Cancelled",
}
SEARCH_PROFILE = {
    "frontend": "Frontend",
    "fullstack": "Full-stack",
    "backend": "Back-end",
    "native": "Native / mobile",
    "devops": "DevOps",
    "custom": "Custom",
}
WEIGHT = {
    "weight_skill": "The skills weight",
    "weight_worktype": "The worktype weight",
    "weight_location": "The location weight",
    "weight_seniority": "The seniority weight",
}


def label(mapping, value):
    """The friendly name for a stored value, or "" for a missing one.

    Unmapped values still come out readable rather than raw, so a category a
    future extractor invents shows up as "Contract", not "contract".
    """
    if not value:
        return ""
    return mapping.get(value) or str(value).replace("_", " ").capitalize()


def options(mapping):
    """A mapping as [{value, label}], for building a <select> on the client."""
    return [{"value": value, "label": text} for value, text in mapping.items()]


def application_groups():
    """`APPLICATION_GROUPS` as JSON the tracker can render its tabs from.

    "Everything" carries no statuses; the client reads an empty list as "no
    filter" rather than "matches nothing", which is why it is not written out
    as every status there is.
    """
    return [
        {"value": value, "label": text, "statuses": list(statuses)}
        for value, text, statuses in APPLICATION_GROUPS
    ]


# ── Dates and times ──────────────────────────────────────────

def utcnow():
    """Naive UTC — the shape every timestamp in the database is stored in."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse(iso):
    """A stored timestamp or date string → datetime, or None if unusable.

    Public because the scan queue compares heartbeats against it — a stored
    stamp is a stored stamp whether it ends up on a page or in a WHERE clause.
    """
    if not iso or not isinstance(iso, str):
        return None
    try:
        return datetime.fromisoformat(iso.strip().replace(" ", "T"))
    except ValueError:
        return None


def _absolute(day, today):
    """'12 Aug', or '12 Aug 2025' once the year stops being obvious."""
    stamp = f"{day.day} {day.strftime('%b')}"
    return stamp if day.year == today.year else f"{stamp} {day.year}"


def relative_date(iso, today=None):
    """Day-granularity age: 'today', '3 days ago', 'last week', '12 Aug'."""
    parsed = parse(iso)
    if parsed is None:
        return ""
    today = today or utcnow().date()
    day = parsed.date()
    delta = (today - day).days
    if delta < 0:
        return _absolute(day, today)  # a board posting into the future
    if delta == 0:
        return "today"
    if delta == 1:
        return "yesterday"
    if delta < 7:
        return f"{delta} days ago"
    if delta < 14:
        return "last week"
    return _absolute(day, today)


def relative_time(iso, now=None):
    """As `relative_date`, with sub-day resolution for today's events."""
    parsed = parse(iso)
    if parsed is None:
        return ""
    now = now or utcnow()
    seconds = max(0.0, (now - parsed).total_seconds())  # 0 absorbs clock skew
    if seconds < 90:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} minutes ago"
    hours = int(seconds // 3600)
    if hours < 24:
        return "an hour ago" if hours == 1 else f"{hours} hours ago"
    return relative_date(iso, today=now.date())


def exact_time(iso):
    """The precise value for a hover tooltip: '8 Aug 2026, 06:50 UTC'.

    Date-only columns (applications.applied_at, jobs.posted_at) have no time to
    show, and printing a midnight that was never recorded would be a small lie.
    """
    parsed = parse(iso)
    if parsed is None:
        return ""
    stamp = f"{parsed.day} {parsed.strftime('%b')} {parsed.year}"
    if len(iso.strip()) <= 10:
        return stamp
    return f"{stamp}, {parsed:%H:%M} UTC"

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
# What the Jobs list can be ordered by. The keys are `db.JOB_ORDER`'s — the SQL
# lives there and the words live here, like every other stored value — and a test
# holds the two sets equal so a new ordering cannot ship without a name.
JOB_SORT = {"score": "Best match", "date": "Newest", "pay": "Best pay"}
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
# The five score components, in the order every chart of them is drawn. This is
# the one place their names are written: the Settings sliders, the breakdown bars
# on a card and on the detail page, and the weight-validation messages below all
# read it. They used to be spelled out in four places, and the landing page had
# already drifted a whole component behind.
SCORE_COMPONENTS = {
    "role": "Role",
    "skills": "Skills",
    "worktype": "Worktype",
    "location": "Location",
    "seniority": "Seniority",
}
# Why a job was cut rather than ranked — `scoring.INELIGIBLE_*`. Written as
# the reason the reader is owed, not as the rule's name: the score on a cut job
# is 0, and a panel explaining that a score is "the average of what is known"
# is a lie about a job that was never averaged.
INELIGIBLE = {
    "field": "Not your trade — the title names work you did not ask for",
    "level": "Above your level — the title asks for someone more senior",
    "reach": "Out of reach — on-site somewhere you cannot get to",
}

# Which stored setting weights each component. `skills` is the one irregular
# pair — `weight_skill`, singular — and it is spelled that way in every row
# already written, so it is mapped rather than derived from the component name.
COMPONENT_WEIGHT = {
    key: "weight_skill" if key == "skills" else f"weight_{key}"
    for key in SCORE_COMPONENTS
}
WEIGHT = {
    COMPONENT_WEIGHT[key]: f"The {text.lower()} weight"
    for key, text in SCORE_COMPONENTS.items()
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


def score_components():
    """`SCORE_COMPONENTS` as JSON the pages can draw bars and sliders from.

    Carries the weight key alongside the label so a page can pair a slider with
    the setting it writes without knowing that `skills` is weighted by
    `weight_skill`. Order is display order, and it is a server fact: the bars on
    a card, the bars on the detail page and the sliders in Settings all draw the
    five in the same sequence because they all read this list.
    """
    return [
        {"key": key, "weight_key": COMPONENT_WEIGHT[key], "label": text}
        for key, text in SCORE_COMPONENTS.items()
    ]


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


# How old a posting may be and still be described in days rather than by its
# date. A month, because on a job board the age *is* the fact: "8 days ago"
# answers "is this still open?" and "last week" — which is what 8 days used to
# read as — throws away the digit that answers it. Past a month the day count
# stops being actionable and the date is the shorter sentence.
DAYS_AGO_LIMIT = 31


def relative_date(iso, today=None):
    """Day-granularity age: 'today', '3 days ago', '8 days ago', '12 Aug'."""
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
    if delta <= DAYS_AGO_LIMIT:
        return f"{delta} days ago"
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

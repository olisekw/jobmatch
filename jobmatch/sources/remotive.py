"""Remotive adapter — public JSON API, remote jobs worldwide.

GET https://remotive.com/api/remote-jobs returns the board's whole feed; salary
is free text, publication_date is ISO.

**One request per scan, not one per search term, and neither half of that is a
preference.** The API ignores every query parameter it documents — `search`,
`category` and `limit` alike — and answers its entire feed to all of them. It
was measured twice, on 2026-09-22 and again on 2026-09-23 with the bare URL
added: `search=python`, `search=developer`, `search=zzqqxxnonsense`,
`category=software-dev`, `limit=5`, `limit=500` and no parameters at all each
returned **the same eighteen ids**. The payload says so itself — `job-count`
and `total-job-count` are both 18 — so there is nothing a request could narrow
towards; the feed *is* the board, and the filtering has to happen here, exactly
as it does for Remote OK. This also means a geography could never work:
`&geo=europe` returned character-for-character the same jobs as no parameter,
so a narrowing guessed at rather than confirmed would have looked like it
worked and silently done nothing. `ctx.regions` is therefore ignored.

And the board asks, in the `0-legal-notice` field of every response it sends:
"there is absolutely no need to request Remotive Job data too frequently …
we advise max. 4 times a day … excessive requests will be blocked." Asking
once per term was **19 requests a scan** on the default profile, and at
`SCAN_INTERVAL_HOURS = 6` that is 76 a day against an advised 4 — for the same
eighteen jobs, nineteen times over. One request per scan puts us exactly on the
number the board named. The delays on the Slovak boards exist for this reason;
this is the same rule written down by the board instead of by us.
"""

import json

from .. import salary as salary_mod
from .base import (
    JobSource,
    http_get,
    match_terms,
    normalize_employment_type,
    posted_cutoff,
    strip_html,
)

API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(JobSource):
    name = "remotive"
    label = "Remotive"
    provides = frozenset({"worktype", "employment_type"})
    has_detail_page = False   # the feed carries the description

    def search(self, page, terms, days, known_ids, ctx):
        ctx.progress(f"Reading the {self.label} feed")
        cutoff = posted_cutoff(days)
        stubs = []
        listed = 0

        # Not caught, and that changed with the request count: the old
        # per-term catch was there so one term failing could not sink the
        # source. There is one request now, so a failure *is* the source
        # failing — and the scan records that as a source error, which is
        # also what keeps the silent-board alarm from firing a second,
        # vaguer complaint about a board that already said what went wrong.
        data = json.loads(http_get(API_URL))

        for item in data.get("jobs") or []:
            if ctx.stopped():
                break
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("id") or "")
            title = (item.get("title") or "").strip()
            if not source_id or not title:
                continue
            # Counted only now: a row we could not read an id and a title off
            # is not a listing this parser saw, whatever the array length says.
            listed += 1

            if source_id in known_ids:
                continue
            haystack = title + " " + " ".join(item.get("tags") or [])
            if not match_terms(haystack, terms):
                continue

            posted_at = (item.get("publication_date") or "")[:10] or None
            if cutoff and posted_at and posted_at < cutoff:
                continue

            salary_text = (item.get("salary") or "").strip() or None
            s_min, s_max, s_cur, s_per = salary_mod.parse_salary(salary_text)

            known_ids.add(source_id)
            stubs.append({
                "source_id": source_id,
                "title": title.lower(),
                "company": (item.get("company_name") or "").strip().lower() or None,
                "location": (
                    (item.get("candidate_required_location") or "").strip().lower() or "remote"
                ),
                "salary": salary_text,
                "freshness": None,
                "link": item.get("url"),
                "description": strip_html(item.get("description")),
                "worktype": "remote",
                "employment_type": normalize_employment_type(item.get("job_type")),
                "posted_at": posted_at,
                "salary_min": s_min,
                "salary_max": s_max,
                "salary_currency": s_cur,
                "salary_period": s_per,
            })

        ctx.seen(listed)
        return stubs

    def fetch_detail(self, page, url):
        return ""

"""Remote OK adapter — public JSON API, remote jobs worldwide.

GET https://remoteok.com/api returns every live listing (element 0 is a
legal-notice stub). Salaries are yearly USD numbers; dates are epoch/ISO.

One URL, no query parameters of any kind — not even the search term, which is
why this adapter filters in Python while the others ask. So `ctx.regions` has
nothing to narrow: the feed is the whole board or nothing.
"""

import datetime
import json

from .base import (
    JobSource,
    http_get,
    match_terms,
    posted_cutoff,
    strip_html,
)

API_URL = "https://remoteok.com/api"


class RemoteOkSource(JobSource):
    name = "remoteok"
    label = "Remote OK"
    provides = frozenset({"worktype"})
    has_detail_page = False   # the feed carries the description

    def search(self, page, terms, days, known_ids, ctx):
        ctx.progress(f"Reading the {self.label} feed")
        items = json.loads(http_get(API_URL))
        cutoff = posted_cutoff(days)
        stubs = []
        # Element 0 is a legal notice, not a job; counting it would make an
        # empty feed look like a feed with one listing on it.
        ctx.seen(sum(1 for i in items if isinstance(i, dict) and i.get("id")))

        for item in items:
            if ctx.stopped():
                break
            if not isinstance(item, dict) or not item.get("id"):
                continue  # element 0 is a legal notice
            source_id = str(item["id"])
            if source_id in known_ids:
                continue

            title = (item.get("position") or "").strip()
            haystack = title + " " + " ".join(item.get("tags") or [])
            if not title or not match_terms(haystack, terms):
                continue

            posted_at = None
            if item.get("epoch"):
                posted_at = datetime.date.fromtimestamp(int(item["epoch"])).isoformat()
            if cutoff and posted_at and posted_at < cutoff:
                continue

            salary_min = float(item["salary_min"]) if item.get("salary_min") else None
            salary_max = float(item["salary_max"]) if item.get("salary_max") else None
            salary_text = None
            if salary_min or salary_max:
                low = int(salary_min or salary_max)
                high = int(salary_max or salary_min)
                salary_text = f"{low:,} – {high:,} usd/year".replace(",", " ")

            description = strip_html(item.get("description"))
            known_ids.add(source_id)
            stubs.append({
                "source_id": source_id,
                "title": title.lower(),
                "company": (item.get("company") or "").strip().lower() or None,
                "location": (item.get("location") or "").strip().lower() or "remote",
                "salary": salary_text,
                "freshness": None,
                "link": item.get("url") or f"https://remoteok.com/l/{source_id}",
                "description": description,
                "worktype": "remote",
                "posted_at": posted_at,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "salary_currency": "USD" if (salary_min or salary_max) else None,
                "salary_period": "year" if (salary_min or salary_max) else None,
            })

        return stubs

    def fetch_detail(self, page, url):
        return ""  # descriptions arrive with the feed

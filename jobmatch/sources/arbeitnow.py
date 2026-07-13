"""Arbeitnow adapter — public JSON API, EU/Germany jobs.

GET https://www.arbeitnow.com/api/job-board-api?page=N (paginated feed,
created_at is epoch). Only remote-flagged jobs are kept, per user decision.
"""

import datetime
import json

from .base import JobSource, http_get, match_terms, normalize_employment_type, posted_cutoff, strip_html

API_URL = "https://www.arbeitnow.com/api/job-board-api?page={page}"
MAX_PAGES = 5


class ArbeitnowSource(JobSource):
    name = "arbeitnow"
    label = "Arbeitnow"

    def search(self, page, terms, days, known_ids, ctx):
        cutoff = posted_cutoff(days)
        stubs = []

        for pg in range(1, MAX_PAGES + 1):
            if ctx.stopped():
                break
            ctx.progress(f"{self.label}: feed page {pg}")
            data = json.loads(http_get(API_URL.format(page=pg)))
            items = data.get("data", [])
            if not items:
                break

            page_too_old = True
            for item in items:
                source_id = item.get("slug") or ""
                posted_at = None
                if item.get("created_at"):
                    posted_at = datetime.date.fromtimestamp(int(item["created_at"])).isoformat()
                if not (cutoff and posted_at and posted_at < cutoff):
                    page_too_old = False

                if not source_id or source_id in known_ids:
                    continue
                if not item.get("remote"):
                    continue  # remote-only, per user decision
                title = (item.get("title") or "").strip()
                haystack = title + " " + " ".join(item.get("tags") or [])
                if not title or not match_terms(haystack, terms):
                    continue
                if cutoff and posted_at and posted_at < cutoff:
                    continue

                job_types = item.get("job_types") or []
                emptype = normalize_employment_type(job_types[0]) if job_types else None

                known_ids.add(source_id)
                stubs.append({
                    "source_id": source_id,
                    "title": title.lower(),
                    "company": (item.get("company_name") or "").strip().lower() or None,
                    "location": (item.get("location") or "").strip().lower() or "remote",
                    "salary": None,
                    "freshness": None,
                    "link": item.get("url"),
                    "description": strip_html(item.get("description")),
                    "worktype": "remote",
                    "employment_type": emptype,
                    "posted_at": posted_at,
                })

            if page_too_old:
                break  # every job on this page is older than the window
            if not ctx.sleep(1.0, 2.5):
                break

        return stubs

    def fetch_detail(self, page, url):
        return ""

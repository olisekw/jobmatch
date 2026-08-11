"""Jobicy adapter — public JSON API, remote jobs with seniority levels.

GET https://jobicy.com/api/v2/remote-jobs?count=50&tag=<term>; jobLevel gives
seniority directly, pubDate is "YYYY-MM-DD HH:MM:SS".
"""

import json
from urllib.parse import quote

from .base import (
    JobSource,
    http_get,
    match_terms,
    normalize_employment_type,
    posted_cutoff,
    strip_html,
)

API_URL = "https://jobicy.com/api/v2/remote-jobs?count=50&tag={term}"

_LEVELS = {"junior": "junior", "entry": "junior", "mid": "medior",
           "middle": "medior", "senior": "senior", "lead": "senior"}


def _seniority(level):
    return _LEVELS.get((level or "").strip().lower())


class JobicySource(JobSource):
    name = "jobicy"
    label = "Jobicy"
    provides = frozenset({"worktype", "seniority", "employment_type"})

    def search(self, page, terms, days, known_ids, ctx):
        cutoff = posted_cutoff(days)
        stubs = []

        for i, term in enumerate(terms, 1):
            if ctx.stopped():
                break
            ctx.progress(f"Searching {self.label} for “{term}” ({i} of {len(terms)})")
            try:
                data = json.loads(http_get(API_URL.format(term=quote(term))))
            except Exception:
                continue

            for item in data.get("jobs", []):
                source_id = str(item.get("id") or "")
                if not source_id or source_id in known_ids:
                    continue
                title = (item.get("jobTitle") or "").strip()
                industry = item.get("jobIndustry") or []
                if isinstance(industry, str):
                    industry = [industry]
                haystack = title + " " + " ".join(industry)
                if not title or not match_terms(haystack, terms):
                    continue

                posted_at = (item.get("pubDate") or "")[:10] or None
                if cutoff and posted_at and posted_at < cutoff:
                    continue

                job_type = item.get("jobType")
                if isinstance(job_type, list):
                    job_type = job_type[0] if job_type else None

                known_ids.add(source_id)
                stubs.append({
                    "source_id": source_id,
                    "title": title.lower(),
                    "company": (item.get("companyName") or "").strip().lower() or None,
                    "location": (item.get("jobGeo") or "").strip().lower() or "remote",
                    "salary": None,
                    "freshness": None,
                    "link": item.get("url"),
                    "description": strip_html(item.get("jobDescription")),
                    "worktype": "remote",
                    "seniority": _seniority(item.get("jobLevel")),
                    "employment_type": normalize_employment_type(job_type),
                    "posted_at": posted_at,
                })

            if not ctx.sleep(1.0, 2.5):
                break

        return stubs

    def fetch_detail(self, page, url):
        return ""

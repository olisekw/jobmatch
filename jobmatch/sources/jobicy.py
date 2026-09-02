"""Jobicy adapter — public JSON API, remote jobs with seniority levels.

GET https://jobicy.com/api/v2/remote-jobs?count=50&tag=<term>; jobLevel gives
seniority directly, pubDate is "YYYY-MM-DD HH:MM:SS".

The one board of the six that lets us say *where* in the request. `&geo=<slug>`
narrows the feed, and asking for a region still returns the postings addressed
to the whole world — a job hiring anywhere hires in Europe too — so narrowing
loses nothing the scorer would have kept. Verified against the live endpoint
before it was relied on (the roadmap said to): an unknown slug is a 400, not a
silently unfiltered answer, which is why `GEO` holds only slugs that were
actually tried.
"""

import json
from urllib.parse import quote

from .. import places
from .base import (
    JobSource,
    http_get,
    match_terms,
    normalize_employment_type,
    posted_cutoff,
    strip_html,
)

API_URL = "https://jobicy.com/api/v2/remote-jobs?count=50&tag={term}"

# `places` regions → the board's own vocabulary. Per-adapter, like `provides`,
# because every board words geography differently and none of them use ours.
#
# `NA` is deliberately absent: the board has no North America slug ("usa" and
# "canada" are separate, and "north-america" is a 400), and two slugs would be
# two crawls of the same board per search term. Jobicy rate-limits — a probe
# hit 429 after fifteen quick requests — so the rule is **one geo or none**:
# narrowing may not cost an extra pass, and asking for everything is what the
# adapter did before this existed.
GEO = {"EU": "europe", "APAC": "apac", "LATAM": "latam"}

_LEVELS = {"junior": "junior", "entry": "junior", "mid": "medior",
           "middle": "medior", "senior": "senior", "lead": "senior"}


def _seniority(level):
    return _LEVELS.get((level or "").strip().lower())


class JobicySource(JobSource):
    name = "jobicy"
    label = "Jobicy"
    provides = frozenset({"worktype", "seniority", "employment_type"})
    has_detail_page = False   # the feed carries the description

    def search(self, page, terms, days, known_ids, ctx):
        cutoff = posted_cutoff(days)
        stubs = []
        region = places.covering_region(ctx.regions)
        geo = GEO.get(region)
        url = API_URL + (f"&geo={geo}" if geo else "")
        where = f" in {places.label(region)}" if geo else ""

        for i, term in enumerate(terms, 1):
            if ctx.stopped():
                break
            ctx.progress(
                f"Searching {self.label}{where} for “{term}” ({i} of {len(terms)})"
            )
            try:
                data = json.loads(http_get(url.format(term=quote(term))))
            except Exception as e:
                ctx.warn(f"“{term}”: {e}")
                continue

            ctx.seen(len(data.get("jobs", [])))
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

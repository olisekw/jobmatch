"""Remotive adapter — public JSON API, remote jobs worldwide.

GET https://remotive.com/api/remote-jobs?search=<term>; salary is free text,
publication_date is ISO.
"""

import json
from urllib.parse import quote

from .. import salary as salary_mod
from .base import JobSource, http_get, match_terms, normalize_employment_type, posted_cutoff, strip_html

API_URL = "https://remotive.com/api/remote-jobs?search={term}&limit=100"


class RemotiveSource(JobSource):
    name = "remotive"
    label = "Remotive"
    provides = frozenset({"worktype", "employment_type"})

    def search(self, page, terms, days, known_ids, ctx):
        cutoff = posted_cutoff(days)
        stubs = []

        for i, term in enumerate(terms, 1):
            if ctx.stopped():
                break
            ctx.progress(f"{self.label}: searching '{term}' ({i}/{len(terms)})")
            try:
                data = json.loads(http_get(API_URL.format(term=quote(term))))
            except Exception:
                continue  # one term failing shouldn't sink the source

            for item in data.get("jobs", []):
                source_id = str(item.get("id") or "")
                if not source_id or source_id in known_ids:
                    continue
                title = (item.get("title") or "").strip()
                haystack = title + " " + " ".join(item.get("tags") or [])
                if not title or not match_terms(haystack, terms):
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
                    "location": (item.get("candidate_required_location") or "").strip().lower() or "remote",
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

            if not ctx.sleep(1.0, 2.5):
                break

        return stubs

    def fetch_detail(self, page, url):
        return ""

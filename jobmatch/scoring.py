"""Weighted job-match scoring.

score = 100 * sum(w_i * c_i for known components) / sum(w_i for known components)

A component is "known" only when the job-side field was actually parsed, so
jobs with unparsed seniority/worktype are not punished for missing data.
"""

import json
import unicodedata
from datetime import datetime

from . import db

SENIORITY_ORDER = {"junior": 0, "medior": 1, "senior": 2}
WORKTYPE_ORDER = {"remote": 0, "hybrid": 1, "onsite": 2}


def strip_diacritics(text):
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _skills_component(job_skills, user_skills):
    """Coverage of the job's requirements by the user's skills (0..1).

    A parsed description with zero detected tech skills scores 0, not
    unknown — for a dev-job matcher the absence of tech keywords is signal.
    """
    job_set = {s.strip().lower() for s in (job_skills or "").split(",") if s.strip()}
    if not job_set or not user_skills:
        return 0.0
    return len(job_set & user_skills) / len(job_set)


def _adjacency_component(job_value, user_value, order):
    if not job_value or job_value not in order:
        return None
    if not user_value or user_value not in order:
        return None
    distance = abs(order[job_value] - order[user_value])
    if distance == 0:
        return 1.0
    if distance == 1:
        return 0.5
    return 0.0


def _location_component(job_location, job_worktype, user_location):
    if not user_location:
        return None
    if job_worktype == "remote":
        return 1.0
    if not job_location:
        return None
    job_norm = strip_diacritics(job_location).lower()
    user_norm = strip_diacritics(user_location).lower()
    return 1.0 if user_norm in job_norm else 0.0


def score_job(job, prefs, weights):
    """Score one job dict/Row. Returns (score 0-100, breakdown dict).

    Jobs whose description was never fetched return (None, {}) — they are
    unscored until a scan enriches them.
    """
    if not (job["description"] or "").strip():
        return None, {}

    components = {
        "skills": _skills_component(job["skills"], prefs["skills"]),
        "worktype": _adjacency_component(job["worktype"], prefs["worktype"], WORKTYPE_ORDER),
        "location": _location_component(job["location"], job["worktype"], prefs["location"]),
        "seniority": _adjacency_component(job["seniority"], prefs["seniority"], SENIORITY_ORDER),
    }

    if (prefs.get("seniority_strict") and prefs["seniority"]
            and job["seniority"] and job["seniority"] != prefs["seniority"]):
        return 0.0, components

    known_weight = sum(weights[name] for name, c in components.items() if c is not None)
    if known_weight <= 0:
        return 0.0, components

    weighted = sum(weights[name] * c for name, c in components.items() if c is not None)
    return round(100 * weighted / known_weight, 1), components


def rescore_all(conn):
    """Recompute and persist match_score + breakdown for every job."""
    prefs = db.get_user_prefs(conn)
    weights = db.get_weights(conn)
    now = datetime.now().isoformat(timespec="seconds")

    updates = []
    for job in conn.execute(
        "SELECT id, description, skills, worktype, seniority, location FROM jobs"
    ):
        score, breakdown = score_job(job, prefs, weights)
        updates.append((score, json.dumps(breakdown) if breakdown else None, now, job["id"]))

    conn.executemany(
        "UPDATE jobs SET match_score = ?, score_breakdown = ?, scored_at = ? WHERE id = ?",
        updates,
    )
    conn.commit()
    return len(updates)

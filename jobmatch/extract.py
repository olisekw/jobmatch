"""Canonical text extractors for job descriptions and resumes.

Single source of truth for the regex extraction that used to be duplicated
across src/fill.py, src/skills.py and config.py. All functions return None
when nothing was detected (the old scripts returned the string "N/A").
"""

import re

import config


def extract_skills(text):
    """Return a sorted list of lowercase skill tokens found in text."""
    if not text or not isinstance(text, str):
        return []
    text_lower = text.lower()
    found = set()
    for pattern in config.CODING_PATTERNS:
        for match in re.findall(pattern, text_lower, re.IGNORECASE):
            clean = re.sub(r'[^a-z0-9\s\.\+#/]', '', match.strip())
            clean = re.sub(r'\s+', ' ', clean).strip()
            if len(clean) > 1 or clean in ("c", "go"):
                found.add(clean)
    return sorted(found)


def _extract_category(text, patterns_dict, priority):
    if not text or not isinstance(text, str):
        return None
    text_lower = text.lower()
    candidates = []
    for category, patterns in patterns_dict.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                candidates.append(category)
                break
    if not candidates:
        return None
    for category in priority:
        if category in candidates:
            return category
    return candidates[0]


def extract_worktype(text):
    return _extract_category(text, config.WORKTYPE_PATTERNS,
                             priority=("remote", "hybrid", "onsite"))


def extract_seniority(text):
    # Highest level named wins: a "senior" ad mentioning "juniors welcome"
    # is still a senior ad.
    return _extract_category(text, config.SENIORITY_PATTERNS,
                             priority=("senior", "medior", "junior"))


def extract_employment_type(text):
    return _extract_category(text, config.EMPTYPE_PATTERNS,
                             priority=("internship", "freelance", "parttime", "fulltime"))


def extract_all(description):
    """Extract every feature from a job description in one pass."""
    return {
        "skills": ", ".join(extract_skills(description)),
        "worktype": extract_worktype(description),
        "seniority": extract_seniority(description),
        "employment_type": extract_employment_type(description),
    }

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
    # Hybrid outranks remote: nearly every hybrid ad also says "home office" or
    # "práca z domu", so whichever *qualifies* that phrase is the real answer.
    # Only an ad with no hybrid marker at all is fully remote.
    return _extract_category(text, config.WORKTYPE_PATTERNS,
                             priority=("hybrid", "remote", "onsite"))


def extract_seniority(text):
    # Highest level named wins: a "senior" ad mentioning "juniors welcome"
    # is still a senior ad.
    return _extract_category(text, config.SENIORITY_PATTERNS,
                             priority=("senior", "medior", "junior"))


def extract_employment_type(text):
    return _extract_category(text, config.EMPTYPE_PATTERNS,
                             priority=("internship", "freelance", "parttime", "fulltime"))


def extract_experience_years(text):
    """The most demanding years-of-experience figure named, or None.

    The *max* of every match, not the first: a description naming both "2+
    years" in one sentence and "5+ years of commercial experience" in another
    is bound by the higher one, the same "most demanding number wins" reading
    `extract_seniority` already gives a word-based "senior" over "junior".

    Patterns run in `config.EXPERIENCE_YEARS_PATTERNS`'s order, and each
    pattern's matches are blanked out of the text before the next one runs —
    otherwise a range ("3-5 years") and the bare "N years experience" pattern
    both match the "5" in "3-5 years of experience", and the range's own lower
    bound (the actual stated minimum) would be lost to it.
    """
    if not text or not isinstance(text, str):
        return None
    text_lower = text.lower()
    found = []
    for pattern in config.EXPERIENCE_YEARS_PATTERNS:
        for match in re.finditer(pattern, text_lower, re.IGNORECASE):
            found.append(int(match.group(1)))
        text_lower = re.sub(pattern, lambda m: " " * len(m.group(0)),
                           text_lower, flags=re.IGNORECASE)
    return max(found) if found else None


def extract_all(description):
    """Extract every feature from a job description in one pass."""
    return {
        "skills": ", ".join(extract_skills(description)),
        "worktype": extract_worktype(description),
        "seniority": extract_seniority(description),
        "employment_type": extract_employment_type(description),
        "experience_years": extract_experience_years(description),
    }

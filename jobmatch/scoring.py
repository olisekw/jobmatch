"""Weighted job-match scoring.

score = 100 * sum(w_i * c_i for known components) / sum(w_i for known components)

A component is "known" only when the job-side field was actually parsed, so
jobs with unparsed seniority/worktype are not punished for missing data.

The exception is `role`, which reads the title: every posting has one, so it
is known for every scored job. That is deliberate. Without it the four
job-side components could all be unknown at once except a description that
mentioned one of your skills, and a "junior ESG consultant" scored the same
100 as a React role — the title, the thing that says what the job actually
is, was the one field nothing read.
"""

import json
import re
import unicodedata
from datetime import datetime

import config

from . import db, places

SENIORITY_ORDER = {"junior": 0, "medior": 1, "senior": 2}
WORKTYPE_ORDER = {"remote": 0, "hybrid": 1, "onsite": 2}

# The ladder a *title* is read on. `SENIORITY_ORDER` grades the extracted
# column and stops at senior; the rungs that matter most to a junior reading a
# job board — lead, architect, head of — are levels that column has no word
# for, and they are stated in titles rather than inferred from prose.
TITLE_LEVELS = {"junior": 0, "medior": 1, "senior": 2, "lead": 3,
                "principal": 4, "architect": 4, "head": 5}

# How a title invites somebody at the bottom of that ladder. Kept here rather
# than in `config.ROLE_LEVEL_ABOVE` because it is the one rung that is not
# "above": these are the words that make a title *safe*, and the range rule
# below needs them to read "(junior - senior)" as the junior opening it is.
TITLE_JUNIOR_WORDS = ["junior", "intern", "internship", "staz", "stazista",
                      "trainee", "graduate", "absolvent", "student",
                      "entry level", "entry-level", "praktikant", "praktikum",
                      "werkstudent"]

# Why somebody cannot take a job at all — recorded in the breakdown so a page
# can say which of the three it was.
INELIGIBLE_FIELD = "field"    # the title names no work this person does
INELIGIBLE_LEVEL = "level"    # it names a level above them
INELIGIBLE_REACH = "reach"    # they cannot work where it is


def strip_diacritics(text):
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _skills_component(job_skills, user_skills):
    """Coverage of the job's requirements by the user's skills (0..1).

    A parsed description with zero detected tech skills scores 0, not
    unknown — for a dev-job matcher the absence of tech keywords is signal.

    Coverage alone was the wrong question when the list is short. Extraction
    finds one skill in 426 of the described jobs in a live pool and none in
    1421, so "you have everything it asked for" was most often a claim about a
    single word — and it scored the same 1.0 as covering a full five-item
    stack. The denominator therefore has a floor (`MIN_SKILL_EVIDENCE`): thin
    evidence can still rank, it just cannot reach the top of the list on its
    own. Above the floor this is exactly the coverage it always was.
    """
    job_set = {s.strip().lower() for s in (job_skills or "").split(",") if s.strip()}
    if not job_set or not user_skills:
        return 0.0
    return len(job_set & user_skills) / max(len(job_set), config.MIN_SKILL_EVIDENCE)


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


# The ladder the role component scores on. Ordered most specific first, because
# the first rung a title reaches is the one it gets: a "React Developer" is
# matched on "react" and never falls through to "developer".
ROLE_EXACT = 1.0        # the title names a technology this person has
ROLE_DISCIPLINE = 0.7   # it names the discipline they are looking for
ROLE_GENERIC_HIT = 0.35  # it names some engineering role, but not theirs
ROLE_MISS = 0.0         # it names none of it — or names another profession


# How many trailing letters a role word may pick up and still be that word.
# Slovak and Czech titles inflect: "webových", "vývojárov", "programátorka".
# Three is enough for the case endings and short of the next real word —
# "web" reaches "webom" but not "webinar", "front" not "frontline".
INFLECTION_LETTERS = 3


def _names(text, phrase, inflected=False):
    """Does `text` name `phrase` as a word rather than as a fragment?

    Titles are prose, so a substring test is not enough: "js" is one of this
    user's skills and a substring of the Czech "jsou", and "ui" sits inside
    "building". Both would have scored a top-rung match on a title about
    neither. Phrases with punctuation ("front-end", "ci/cd") still work,
    because only the ends are anchored.

    `inflected` relaxes the closing anchor for the role vocabulary, which is
    written in the languages the Slovak and Czech boards post in. It stays off
    for skills — a technology's name does not decline, and "js" plus two
    letters is the Czech word for "are".
    """
    tail = r"(?!\w)"
    if inflected and len(phrase) >= 4:
        tail = r"[a-z]{0," + str(INFLECTION_LETTERS) + r"}(?!\w)"
    return re.search(r"(?<!\w)" + re.escape(phrase) + tail, text) is not None


def user_disciplines(terms):
    """Which of the disciplines `config` knows this user's search terms name.

    Derived rather than stored: the terms are already a setting the user fills
    in, and asking them a second time in different words is how two answers
    start to disagree. Level words come out first — see `ROLE_LEVEL_WORDS`.

    A term matches a discipline word when either contains the other, so the
    "front" this user actually typed finds "frontend". That is a prefix test
    on purpose and it needs a floor: two characters would let almost anything
    match almost anything, so only terms of three or more can match by prefix.
    """
    wanted = {strip_diacritics(str(t)).strip().lower() for t in (terms or [])}
    wanted = {t for t in wanted if t} - config.ROLE_LEVEL_WORDS
    found = set()
    for discipline, words in config.ROLE_DISCIPLINES.items():
        for word in words:
            if any(t == word or (len(t) >= 3 and (t in word or word in t))
                   for t in wanted):
                found.add(discipline)
                break
    return found


def _role_component(job_title, prefs):
    """Does the title name work this person does (0..1)?

    Always known — every posting has a title — which is the point: the other
    four components can all be unknown at once, and before this one a job
    could reach 100 on a single word found in its description. A miss is a
    real 0.0 and not `None`, because a title naming work the user did not ask
    for is an answer, not missing data.
    """
    title = strip_diacritics(job_title or "").lower()
    if not title.strip():
        return None

    if any(_names(title, skill) for skill in prefs.get("skills") or ()):
        return ROLE_EXACT

    for discipline in sorted(prefs.get("disciplines") or ()):
        if any(_names(title, w, inflected=True)
               for w in config.ROLE_DISCIPLINES.get(discipline, ())):
            return ROLE_DISCIPLINE

    # Another profession, asked only now: the two rungs above have already had
    # their say, so a dev title that merely mentions another industry keeps the
    # rung it earned. Below here, a generic hit is the only thing left to win
    # on, and "engineer" is a word a factory uses too.
    if any(_names(title, word, inflected=True) for word in config.ROLE_OTHER_FIELDS):
        return ROLE_MISS

    if any(_names(title, word, inflected=True) for word in config.ROLE_GENERIC):
        return ROLE_GENERIC_HIT
    return ROLE_MISS


def title_levels(job_title):
    """Every level this title names, as `TITLE_LEVELS` ranks.

    A set, not one answer, because titles name ranges. Matched with the same
    inflection allowance the role vocabulary uses — Slovak titles decline —
    and at word boundaries, so "sr" cannot be found inside another word.
    """
    title = strip_diacritics(job_title or "").lower()
    if not title.strip():
        return set()
    found = set()
    for word in TITLE_JUNIOR_WORDS:
        if _names(title, word, inflected=True):
            found.add(TITLE_LEVELS["junior"])
            break
    for level, words in config.ROLE_LEVEL_ABOVE.items():
        if any(_names(title, w, inflected=True) for w in words):
            found.add(TITLE_LEVELS[level])
    return found


def level_floor(job_title):
    """The lowest level this title invites, or None if it names none.

    The *lowest*, because a title naming a range is an opening at the bottom of
    it: "webový manažér (junior - senior)" invites a junior by name, and reading
    only the highest word would have cut an ad that was addressed to them.
    """
    named = title_levels(job_title)
    return min(named) if named else None


def _reachable(job, prefs):
    """Can this person work where this job is? True / False / None if unknown.

    `jobs.worktype` is not the whole answer, because on a board that does not
    declare it that column was read out of the ad's prose: "možnosť práce z
    domu" in an ad for an office on Bottova 2a stores `remote`, and a perk is
    not a work permit. The place field is the one the board filled in on
    purpose, so when it names a town in this person's own country that is not
    their town, that settles it — a commute they cannot make, whatever the
    prose said. Only once no such town is named does `worktype` get asked, and
    then the question is reach rather than distance, over the same
    `places.reachable_codes()` expansion the filter uses.

    Unknown stays unknown: a row with no place and no work mode is not evidence
    that somebody cannot take it.
    """
    town = strip_diacritics(prefs.get("location") or "").lower().strip()
    loc = strip_diacritics(job["location"] or "").lower()
    if town and town in loc:
        return True
    if loc and any(city != town and _names(loc, city) for city in config.SK_CITIES):
        return False
    if job["worktype"] == "remote":
        reachable = prefs.get("reachable")
        hiring_in = places.stored_codes(job["countries"], job["country"])
        if not reachable or not hiring_in:
            return None
        return bool(reachable & hiring_in)
    if not town or not loc:
        return None
    return False


def ineligible(job, prefs, role):
    """Why this person cannot take this job at all — or None if they can.

    Deliberately not a score. A score ranks jobs somebody could take, and these
    three are not weak answers but non-answers, which is why weighting them
    could never have worked: before this existed, 96 of 245 fresh Profesia
    postings — a receptionist, a toolmaker, a junior project manager, an
    insurance intern — all sat at exactly 37.6 on a frontend developer's list,
    comfortably above his threshold, because the four job-side components
    cannot tell what a job *is* and nothing had asked whether he was eligible
    for it. Each test refuses to fire on missing data, so a thin row is still
    ranked rather than hidden.
    """
    if role == ROLE_MISS:
        return INELIGIBLE_FIELD

    floor = level_floor(job["title"])
    mine = TITLE_LEVELS.get(prefs.get("seniority") or "")
    if floor is not None and mine is not None and floor > mine:
        return INELIGIBLE_LEVEL

    if _reachable(job, prefs) is False:
        return INELIGIBLE_REACH
    return None


def _location_component(job, prefs):
    """Can this person take this job, where it is (0..1, or None for unknown)?

    Two different questions behind one component, because "remote" changes what
    the word location means:

    - **Remote** is not automatically a fit. A remote job is still hired out of
      somewhere, and a US-only role is no use to somebody in Bratislava — so it
      is judged against the places the posting names (`jobs.countries`) and the
      set of places the user can work in (`prefs["reachable"]`, expanded once
      by `places`) — two sets, and any overlap is a fit, because a posting
      hiring in five places is hiring in all five. Worldwide postings satisfy
      everybody, which is a rule inside that expansion.
    - **Onsite and hybrid** are judged on the town, as before, because that is a
      commute and no country rule answers it: Prague is in Europe and is still
      not a commute from Bratislava.

    A row nobody could place, and a user who has answered neither question, both
    return None — unknown, and so a hatched bar rather than a zero.
    """
    if job["worktype"] == "remote":
        reachable = prefs.get("reachable")
        hiring_in = places.stored_codes(job["countries"], job["country"])
        if not reachable or not hiring_in:
            return None
        return 1.0 if reachable & hiring_in else 0.0
    if not prefs["location"] or not job["location"]:
        return None
    job_norm = strip_diacritics(job["location"]).lower()
    user_norm = strip_diacritics(prefs["location"]).lower()
    return 1.0 if user_norm in job_norm else 0.0


def score_job(job, prefs, weights):
    """Score one job dict/Row. Returns (score 0-100, breakdown dict).

    Jobs whose description was never fetched return (None, {}) — they are
    unscored until a scan enriches them.
    """
    if not (job["description"] or "").strip():
        return None, {}

    components = {
        "role": _role_component(job["title"], prefs),
        "skills": _skills_component(job["skills"], prefs["skills"]),
        "worktype": _adjacency_component(job["worktype"], prefs["worktype"], WORKTYPE_ORDER),
        "location": _location_component(job, prefs),
        "seniority": _adjacency_component(job["seniority"], prefs["seniority"], SENIORITY_ORDER),
    }

    if (prefs.get("seniority_strict") and prefs["seniority"]
            and job["seniority"] and job["seniority"] != prefs["seniority"]):
        return 0.0, components

    # Eligibility is asked after the components so the breakdown still shows
    # what the job looked like, and the reason sits beside them: a page that
    # hides these jobs can still say why one is hidden.
    if prefs.get("strict_match"):
        reason = ineligible(job, prefs, components["role"])
        if reason:
            components["ineligible"] = reason
            return 0.0, components

    known_weight = sum(weights[name] for name, c in components.items() if c is not None)
    if known_weight <= 0:
        return 0.0, components

    weighted = sum(weights[name] * c for name, c in components.items() if c is not None)
    return round(100 * weighted / known_weight, 1), components


def rescore_user(conn, user_id):
    """Recompute and persist one user's match_score + breakdown for every job.

    Scores live in `user_jobs`, so two users with different weights read the
    same shared `jobs` pool through their own row. Missing rows are materialized
    first — a user who signed up after the last scan has none yet.
    """
    db.ensure_user_jobs(conn, user_id)
    prefs = db.get_user_prefs(conn, user_id)
    weights = db.get_weights(conn, user_id)
    now = datetime.now().isoformat(timespec="seconds")

    updates = []
    for job in conn.execute(
        """SELECT j.id, j.title, j.description, j.skills, j.worktype, j.seniority,
                  j.location, j.country, j.countries
           FROM jobs j JOIN user_jobs uj ON uj.job_id = j.id
           WHERE uj.user_id = :user_id""",
        {"user_id": user_id},
    ):
        score, breakdown = score_job(job, prefs, weights)
        updates.append({
            "score": score,
            "breakdown": json.dumps(breakdown) if breakdown else None,
            "now": now,
            "user_id": user_id,
            "job_id": job["id"],
        })

    conn.executemany(
        "UPDATE user_jobs SET match_score = :score, score_breakdown = :breakdown, "
        "scored_at = :now WHERE user_id = :user_id AND job_id = :job_id",
        updates,
    )
    conn.commit()
    return len(updates)


def rescore_all_users(conn):
    """Rescore every user — what a finished scan triggers. Returns rows written."""
    user_ids = [row["id"] for row in conn.execute("SELECT id FROM users ORDER BY id")]
    return sum(rescore_user(conn, user_id) for user_id in user_ids)

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

# The engagements actually being hunted, as a title names them. Split out of
# the junior rung below because the two words say different things: "junior"
# states a rung on the ladder, which is the seniority component's question,
# while these name the *kind of opening* — an internship, a working-student
# post, a graduate programme — and that is a positive signal in its own right.
# Titles of this shape frequently name no trade at all ("Trainee programme",
# "Absolvent — IT"), which is why `_role_component` gives them a rung rather
# than reading them as a miss, and so why they are their own list.
TITLE_ENTRY_WORDS = ["intern", "internship", "staz", "stazista", "trainee",
                     "graduate", "absolvent", "student", "entry level",
                     "entry-level", "praktikant", "praktikum", "werkstudent"]

# How a title invites somebody at the bottom of that ladder. Kept here rather
# than in `config.ROLE_LEVEL_ABOVE` because it is the one rung that is not
# "above": these are the words that make a title *safe*, and the range rule
# below needs them to read "(junior - senior)" as the junior opening it is.
# "junior" is the one that is only ever a level, so it is only ever here.
TITLE_JUNIOR_WORDS = ["junior", *TITLE_ENTRY_WORDS]

# Why somebody cannot take a job at all — recorded in the breakdown so a page
# can say which of the three it was.
INELIGIBLE_FIELD = "field"    # the title names no work this person does
INELIGIBLE_LEVEL = "level"    # it names a level above them
INELIGIBLE_REACH = "reach"    # they cannot work where it is


def strip_diacritics(text):
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _skills_component(job_skills, user_skills, near_skills=()):
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
    have = job_set & set(user_skills)
    # A requirement he does not have but could pick up counts for part of one,
    # which is `MISSION.md`'s "a job in a neighbouring technology is not a
    # miss" expressed where coverage is measured rather than only on the title.
    near = (job_set - have) & set(near_skills or ())
    covered = len(have) + config.SKILL_ADJACENT_CREDIT * len(near)
    return covered / max(len(job_set), config.MIN_SKILL_EVIDENCE)


def _grade(distance):
    """One rung away is half a fit, two is none.

    Pulled out of `_adjacency_component` because the seniority component now
    reads a *title* against the six-rung `TITLE_LEVELS` ladder rather than the
    three-rung extracted column, and two ladders grading distance differently
    is how the same gap starts scoring two ways.
    """
    if distance == 0:
        return 1.0
    if distance == 1:
        return 0.5
    return 0.0


def _adjacency_component(job_value, user_value, order):
    if not job_value or job_value not in order:
        return None
    if not user_value or user_value not in order:
        return None
    return _grade(abs(order[job_value] - order[user_value]))


# The ladder the role component scores on. Ordered most specific first, because
# the first rung a title reaches is the one it gets: a "React Developer" is
# matched on "react" and never falls through to "developer".
ROLE_EXACT = 1.0        # the title names a technology this person has
ROLE_ADJACENT = 0.85    # it names one next to a technology they have
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


def adjacent_skills(user_skills):
    """Technologies next to the ones this person has (`config.SKILL_ADJACENCY`).

    Their own skills are removed from the result, so the two role rungs cannot
    both fire on one word and the adjacent rung is only ever the *second* best
    answer a title can give.

    Expanded once per user rather than once per job — `db.get_user_prefs` keeps
    it beside `reachable` and `disciplines` for the same reason: scoring a
    thousand jobs should not re-read the vocabulary a thousand times.
    """
    have = {str(s).strip().lower() for s in (user_skills or ()) if str(s).strip()}
    near = set()
    for group in config.SKILL_ADJACENCY:
        members = {m.lower() for m in group}
        if members & have:
            near |= members
    return near - have


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
    # Somebody who named both ends named the middle. Without this, "senior full
    # stack developer" scored the generic 0.35 on the list of a developer whose
    # terms say frontend *and* backend — his own job, read as somebody else's.
    if {"frontend", "backend"} <= found:
        found.add("fullstack")
    return found


def entry_level(job_title):
    """Does the title name an entry-level engagement?

    A student, graduate, internship or trainee opening — the engagements being
    hunted, per `MISSION.md`, rather than full-time mid-level roles. Read off
    the title because that is where a posting states who it is addressed to;
    `jobs.employment_type` names the contract, which is a different question
    and silent on most Slovak ads.

    Not the same question as "does this title name a level at or below mine"
    (`title_levels`): plain "junior" is a rung on the ladder and belongs to the
    seniority component, while these words say what *kind* of opening it is.
    """
    title = strip_diacritics(job_title or "").lower()
    return any(_names(title, word, inflected=True) for word in TITLE_ENTRY_WORDS)


def names_other_field(job_title):
    """Does the title name somebody else's profession? (`ROLE_OTHER_FIELDS`)

    One derivation with two readers — the role ladder's fourth rung and the
    entry-level rung that sits beside it — because "is this another trade?"
    must be the same answer to both. An entry-level opening in another trade
    ("absolvent — účtovník") is still another trade.
    """
    title = strip_diacritics(job_title or "").lower()
    return any(_names(title, word, inflected=True)
               for word in config.ROLE_OTHER_FIELDS)


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

    # One rung down: a stack he could pick up. "Angular developer" used to land
    # on the generic rung — level with a maintenance engineer — because the
    # word is in no discipline's vocabulary and in nobody's CV.
    if any(_names(title, skill) for skill in prefs.get("near_skills") or ()):
        return ROLE_ADJACENT

    for discipline in sorted(prefs.get("disciplines") or ()):
        if any(_names(title, w, inflected=True)
               for w in config.ROLE_DISCIPLINES.get(discipline, ())):
            return ROLE_DISCIPLINE

    # Another profession, asked only now: the two rungs above have already had
    # their say, so a dev title that merely mentions another industry keeps the
    # rung it earned. Below here, a generic hit is the only thing left to win
    # on, and "engineer" is a word a factory uses too.
    if names_other_field(title):
        return ROLE_MISS

    # A title has to name the work to earn this rung, entry-level or not. The
    # push-through that used to sit here handed any title containing "študent"
    # or "absolvent" the generic rung so the field test could not cut it. It
    # saved the occasional untraded "Trainee programme" and admitted a flood:
    # on Profesia a student title is a shop floor, an assembly line, a law
    # firm's filing or an assistant's desk, and four were on the first real
    # list — "hľadáme študentov do tímov", "brigádnik — študentka". Coding
    # jobs only, which is the brief, so a student ad naming no coding is a
    # miss exactly like any other ad naming none.
    #
    # The openings actually being hunted lose nothing, because they reach the
    # rungs above this one: "Trainee frontend developer" is matched on its
    # discipline, "Absolvent — programátor" on the word programátor. And
    # `entry_level` keeps its other job, the "Entry level" tag on the card; it
    # simply stops deciding eligibility.
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


def experience_floor(job):
    """The level an explicit years-of-experience requirement implies, or None.

    A different kind of evidence from `job["seniority"]` below: that column is
    a categorical word match ("senior", "lead developer") that also fires on
    prose with nothing to do with the role's own level ("a leading Slovak
    company"), which is exactly why the eligibility cut refuses to read it. A
    parsed number — "5+ years of experience", "minimálne 5 rokov praxe" — is
    not that kind of false positive: naming a specific year count is hard to
    do by accident, so it is allowed to act like title-grade evidence.
    """
    years = job["experience_years"]
    if years is None:
        return None
    floor = None
    for threshold, level in sorted(config.EXPERIENCE_YEARS_LEVEL.items()):
        if years >= threshold:
            floor = TITLE_LEVELS[level]
    return floor


def job_level(job):
    """The level this posting is addressed to, on the `TITLE_LEVELS` ladder.

    The title's lowest rung when it names one, an explicit years-of-experience
    requirement next, the extracted `jobs.seniority` column only when neither
    says anything, and None when nothing at all does. One derivation, so the
    score and the strict-level gate cannot disagree about what level a job is
    — they used to read different columns.

    The title goes first for the reason the eligibility cut reads it: a title
    states a level deliberately, while that column is pulled out of prose that
    says "lead a small team" and "a leading Slovak company" about jobs that are
    neither — and the rungs a junior most needs to see, intern and trainee and
    graduate at one end, lead and head-of at the other, are ones the column has
    no word for at all. The two ladders agree on junior/medior/senior, so a row
    whose title is silent scores exactly as it did before. Years-of-experience
    sits between the two for the same reason it is allowed into the cut below:
    higher-precision than the column, lower than a title that states a level
    on purpose.
    """
    floor = level_floor(job["title"])
    if floor is not None:
        return floor
    floor = experience_floor(job)
    if floor is not None:
        return floor
    return TITLE_LEVELS.get((job["seniority"] or "").strip().lower())


def _seniority_component(job, prefs):
    """How far this job's level is from the user's (0..1, None if unknown).

    Unknown either way stays unknown — a posting that states no level and a
    user who has not said theirs are both missing data, and so a hatched bar
    rather than a zero.
    """
    mine = TITLE_LEVELS.get(prefs.get("seniority") or "")
    level = job_level(job)
    if level is None or mine is None:
        return None
    return _grade(abs(level - mine))


# Reach has three answers, not two. "Can he get to it" and "how good is the
# place" used to be asked by two functions reading different evidence — the cut
# consulted the place field and the component did not — so the same Bratislava
# job that `ineligible` wanted to throw away was scoring a *perfect* 1.0 on its
# location. One derivation, three outcomes, both readers.
REACH_OK = 1.0       # his own town, or genuinely remote and hiring where he is
REACH_CLAIMED = 0.5  # another town in his country, but the ad claims remote
REACH_NO = 0.0       # a commute he cannot make, or remote from out of reach


def reach(job, prefs):
    """How well this person can work where this job is (1.0 / 0.5 / 0.0 / None).

    `jobs.worktype` is not the whole answer, because on a board that does not
    declare it that column was read out of the ad's prose: "možnosť práce z
    domu" in an ad for an office on Bottova 2a stores `remote`, and a perk is
    not a work permit. The place field is the one the board filled in on
    purpose, so when it names a town in this person's own country that is not
    their town, the place field wins.

    It no longer wins *outright*, which is the whole difference from the
    two-state version this replaces. A Slovak job outside his town whose ad
    says remote is one he might be able to take and might not — the prose
    cannot tell those apart — so it keeps half a fit and stays on the list,
    ranked below work he can certainly do. Only a town he cannot commute to
    with no remote claim at all is a `REACH_NO`, and that is the one
    `ineligible` cuts.

    Unknown stays unknown: a row with no place and no work mode is not evidence
    that somebody cannot take it.
    """
    town = strip_diacritics(prefs.get("location") or "").lower().strip()
    loc = strip_diacritics(job["location"] or "").lower()
    if town and town in loc:
        return REACH_OK
    # `town and`: with no answer to "where are you", the town in a posting is
    # not evidence about anybody. Every test here refuses to fire on missing
    # data, because `ineligible` reads this one and a thin row must still be
    # ranked rather than hidden.
    if town and loc and any(city != town and _names(loc, city)
                            for city in config.SK_CITIES):
        # Half, not nothing, when the ad claims remote — see above.
        return REACH_CLAIMED if job["worktype"] == "remote" else REACH_NO
    if job["worktype"] == "remote":
        # Remote is not automatically a fit: a remote job is still hired out of
        # somewhere, and a US-only role is no use to somebody in Slovakia. Two
        # sets, and any overlap is a fit, because a posting hiring in five
        # places is hiring in all five — worldwide postings satisfy everybody,
        # which is a rule inside that expansion.
        reachable = prefs.get("reachable")
        hiring_in = places.stored_codes(job["countries"], job["country"])
        if not reachable or not hiring_in:
            return None
        return REACH_OK if reachable & hiring_in else REACH_NO
    if not town or not loc:
        return None
    return REACH_NO


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

    # `level_floor`/`experience_floor`, not `job_level`: a *cut* needs
    # title-grade evidence. The extracted `jobs.seniority` column is good
    # enough to rank a job with and not good enough to hide one — "a leading
    # Slovak company" in the prose of a graduate advert would otherwise throw
    # away the opening it is advertising. An explicit years count is a
    # different kind of evidence, which is why it is allowed in here beside
    # the title: "Software Developer" naming no level at all, next to
    # "minimálne 5 rokov praxe" in the body, is exactly the senior job in
    # junior's clothing this cut exists to catch.
    floor = max((f for f in (level_floor(job["title"]), experience_floor(job))
                if f is not None), default=None)
    mine = TITLE_LEVELS.get(prefs.get("seniority") or "")
    if floor is not None and mine is not None and floor > mine:
        return INELIGIBLE_LEVEL

    # Only an outright no. A job whose ad claims remote from another Slovak
    # town is `REACH_CLAIMED` and stays on the list at half a location.
    if reach(job, prefs) == REACH_NO:
        return INELIGIBLE_REACH
    return None


def _location_component(job, prefs):
    """Can this person take this job, where it is (0..1, or None for unknown)?

    The component *is* `reach`, and that is the point: the scorer and the cut
    read one derivation, so they cannot disagree about the same job the way
    they did before. Onsite and hybrid are judged on the town, because that is
    a commute and no country rule answers it — Prague is in Europe and is
    still not a commute from Bratislava. Remote is judged on the places the
    posting names against the places this person may work in, because a remote
    job is still hired out of somewhere.

    A row nobody could place, and a user who has answered neither question,
    both return None — unknown, and so a hatched bar rather than a zero.
    """
    return reach(job, prefs)


def score_job(job, prefs, weights):
    """Score one job dict/Row. Returns (score 0-100, breakdown dict).

    Jobs whose description was never fetched return (None, {}) — they are
    unscored until a scan enriches them.
    """
    if not (job["description"] or "").strip():
        return None, {}

    components = {
        "role": _role_component(job["title"], prefs),
        "skills": _skills_component(job["skills"], prefs["skills"],
                                    prefs.get("near_skills")),
        "worktype": _adjacency_component(job["worktype"], prefs["worktype"], WORKTYPE_ORDER),
        "location": _location_component(job, prefs),
        "seniority": _seniority_component(job, prefs),
    }

    # "Only my exact level", asked of `job_level` rather than of the extracted
    # column alone: a title that says "Trainee frontend developer" is addressed
    # to a junior whatever its prose mentions, and gating on the column here
    # while scoring on the title above would be one setting with two opinions.
    mine = TITLE_LEVELS.get(prefs.get("seniority") or "")
    level = job_level(job)
    if prefs.get("seniority_strict") and mine is not None and level is not None:
        if level != mine:
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
                  j.experience_years, j.location, j.country, j.countries
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

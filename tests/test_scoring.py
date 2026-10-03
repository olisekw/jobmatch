"""Correctness tests for the weighted match scoring (`jobmatch.scoring`).

The load-bearing invariant (see CLAUDE.md / PROJECT.md) is that scoring runs
over *known* components only — a job whose worktype/seniority never parsed must
not be punished for the missing data. `test_missing_components_do_not_dilute`
is the guard for that; the rest pin the individual component curves, the strict
seniority gate, and the rounding/edge behavior of `score_job`.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import unittest

import config
from jobmatch import places, scoring

WEIGHTS_EQUAL = {"skills": 1.0, "role": 1.0, "worktype": 1.0,
                 "location": 1.0, "seniority": 1.0}


def make_job(description="Python developer wanted.", skills="",
             worktype=None, location=None, seniority=None, country=None,
             countries=None, title=""):
    """A job in the dict shape `score_job` reads (mirrors the DB Row columns).

    `countries` defaults to the packed form of `country`, which is what a
    scanned row holds — pass it explicitly for a posting naming several places.

    `title` defaults to empty, which makes the role component unknown and so
    keeps it out of every test that is not about it. A real posting always has
    one — `RoleComponentTests` is where that is exercised.
    """
    return {
        "title": title,
        "description": description,
        "skills": skills,
        "worktype": worktype,
        "location": location,
        "seniority": seniority,
        "country": country,
        "countries": countries if countries is not None else places.pack([country]),
    }


def make_prefs(skills=None, worktype=None, location=None,
               seniority=None, seniority_strict=False, regions=None,
               disciplines=None, strict_match=False):
    """User prefs in the shape `db.get_user_prefs` returns (skills is a set).

    `regions` is the codes a user picked; `reachable` is the expansion the
    scorer actually tests against, built here by the same `places` call
    `db.get_user_prefs` makes — so a test cannot accidentally assert against a
    set the app would never produce.
    """
    return {
        "skills": set(skills or []),
        "disciplines": set(disciplines or []),
        "worktype": worktype,
        "location": location,
        "seniority": seniority,
        "seniority_strict": seniority_strict,
        "strict_match": strict_match,
        "regions": set(regions or []),
        "reachable": places.reachable_codes(regions or []),
    }


class DescriptionGateTests(unittest.TestCase):
    def test_no_description_is_unscored(self):
        # No fetched description -> (None, {}), shown unscored until a scan enriches it.
        self.assertEqual(scoring.score_job(make_job(description=""),
                                           make_prefs(), WEIGHTS_EQUAL), (None, {}))

    def test_whitespace_only_description_is_unscored(self):
        score, breakdown = scoring.score_job(make_job(description="   \n\t"),
                                             make_prefs(skills=["python"]), WEIGHTS_EQUAL)
        self.assertIsNone(score)
        self.assertEqual(breakdown, {})


class SkillsComponentTests(unittest.TestCase):
    def test_coverage_is_overlap_over_job_requirements(self):
        # User covers 2 of the job's 3 skills -> 2/3; only skills is "known" here.
        score, comp = scoring.score_job(
            make_job(skills="python, react, sql"),
            make_prefs(skills=["python", "react"]), WEIGHTS_EQUAL)
        self.assertAlmostEqual(comp["skills"], 2 / 3)
        self.assertEqual(score, 66.7)

    def test_full_coverage_scores_100(self):
        # Three detected skills is the evidence floor, so covering all of them
        # is the real 1.0 — see `test_one_detected_skill_cannot_reach_the_top`.
        score, comp = scoring.score_job(
            make_job(skills="python, react, sql"),
            make_prefs(skills=["python", "react", "sql", "go"]), WEIGHTS_EQUAL)
        self.assertEqual(comp["skills"], 1.0)
        self.assertEqual(score, 100.0)

    def test_parsed_description_with_no_skill_overlap_scores_zero(self):
        # A parsed dev ad with zero matching skills is 0, not "unknown".
        _, comp = scoring.score_job(
            make_job(skills="cobol, fortran"),
            make_prefs(skills=["python"]), WEIGHTS_EQUAL)
        self.assertEqual(comp["skills"], 0.0)

    def test_empty_job_skills_is_zero_component(self):
        _, comp = scoring.score_job(make_job(skills=""),
                                    make_prefs(skills=["python"]), WEIGHTS_EQUAL)
        self.assertEqual(comp["skills"], 0.0)


class AdjacencyComponentTests(unittest.TestCase):
    def test_worktype_distance_curve(self):
        def wt(job_worktype, pref_worktype):
            _, comp = scoring.score_job(
                make_job(worktype=job_worktype),
                make_prefs(worktype=pref_worktype), WEIGHTS_EQUAL)
            return comp["worktype"]

        self.assertEqual(wt("remote", "remote"), 1.0)   # exact
        self.assertEqual(wt("remote", "hybrid"), 0.5)   # one step
        self.assertEqual(wt("remote", "onsite"), 0.0)   # two steps

    def test_seniority_distance_curve(self):
        def sen(job_sen, pref_sen):
            _, comp = scoring.score_job(
                make_job(seniority=job_sen),
                make_prefs(seniority=pref_sen), WEIGHTS_EQUAL)
            return comp["seniority"]

        self.assertEqual(sen("junior", "junior"), 1.0)
        self.assertEqual(sen("junior", "medior"), 0.5)
        self.assertEqual(sen("junior", "senior"), 0.0)

    def test_unparsed_side_is_unknown_not_zero(self):
        # Job worktype missing -> component is None (unknown), distinct from 0.0.
        _, comp = scoring.score_job(make_job(worktype=None),
                                    make_prefs(worktype="remote"), WEIGHTS_EQUAL)
        self.assertIsNone(comp["worktype"])

        # Pref worktype missing -> also unknown.
        _, comp = scoring.score_job(make_job(worktype="remote"),
                                    make_prefs(worktype=None), WEIGHTS_EQUAL)
        self.assertIsNone(comp["worktype"])


class LocationComponentTests(unittest.TestCase):
    """Onsite is a commute; remote is a work permit. Two rules, one component."""

    def test_remote_job_in_a_reachable_country_is_full_score(self):
        _, comp = scoring.score_job(
            make_job(worktype="remote", country="SK"),
            make_prefs(regions=["SK", "EU"]), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 1.0)

    def test_remote_job_somewhere_unreachable_is_not(self):
        # The bug this component was rewritten for: a US-only remote role used
        # to score full marks for a user in Bratislava, ranking exactly level
        # with the EU roles it should have been beaten by.
        _, comp = scoring.score_job(
            make_job(worktype="remote", country="US"),
            make_prefs(regions=["SK", "EU"]), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 0.0)

    def test_remote_job_elsewhere_in_the_region_is_reachable(self):
        # "Europe" in the preference covers the countries inside it.
        _, comp = scoring.score_job(
            make_job(worktype="remote", country="PT"),
            make_prefs(regions=["SK", "EU"]), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 1.0)

    def test_job_posted_to_a_whole_region_reaches_a_country_preference(self):
        # And the expansion runs the other way too: somebody who can only work
        # in Slovakia is still served by a posting addressed to Europe.
        _, comp = scoring.score_job(
            make_job(worktype="remote", country="EU"),
            make_prefs(regions=["SK"]), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 1.0)

    def test_worldwide_job_reaches_everybody(self):
        _, comp = scoring.score_job(
            make_job(worktype="remote", country="ANY"),
            make_prefs(regions=["SK"]), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 1.0)

    def test_a_posting_hiring_in_five_places_is_reachable_from_any_of_them(self):
        """One overlap is a fit. Storing only the first place a posting named
        made "LATAM, Europe, USA, Canada, APAC" a `US` job and scored it 0 for
        a European, which is the job this whole component exists to find."""
        _, comp = scoring.score_job(
            make_job(worktype="remote", country="EU",
                     countries=places.pack(("US", "CA", "EU", "LATAM", "APAC"))),
            make_prefs(regions=["SK", "EU"]), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 1.0)

    def test_a_posting_naming_several_unreachable_places_is_still_zero(self):
        """The fix must not hand everybody every job — a set that overlaps
        nothing the user can reach is as unreachable as one country was."""
        _, comp = scoring.score_job(
            make_job(worktype="remote", country="US",
                     countries=places.pack(("US", "CA", "IN"))),
            make_prefs(regions=["SK", "EU"]), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 0.0)

    def test_a_row_from_before_the_set_column_still_scores(self):
        """`jobs.countries` is NULL between the column being added and the
        backfill; a remote job must not go unscored for that window."""
        _, comp = scoring.score_job(
            make_job(worktype="remote", country="PT", countries=None),
            make_prefs(regions=["SK", "EU"]), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 1.0)

    def test_remote_job_nobody_could_place_is_unknown(self):
        # Unplaced is not unreachable — an empty bar reads as a zero, so this
        # has to stay None and be hatched.
        _, comp = scoring.score_job(
            make_job(worktype="remote", country=None, countries=None),
            make_prefs(regions=["SK", "EU"]), WEIGHTS_EQUAL)
        self.assertIsNone(comp["location"])

    def test_remote_job_is_unknown_when_the_user_said_nothing(self):
        _, comp = scoring.score_job(
            make_job(worktype="remote", country="US"),
            make_prefs(location="bratislava"), WEIGHTS_EQUAL)
        self.assertIsNone(comp["location"])

    def test_substring_city_match(self):
        _, comp = scoring.score_job(
            make_job(worktype="onsite", location="Bratislava, Slovakia"),
            make_prefs(location="bratislava"), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 1.0)

    def test_diacritics_are_stripped_before_matching(self):
        _, comp = scoring.score_job(
            make_job(worktype="onsite", location="Košice"),
            make_prefs(location="kosice"), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 1.0)

    def test_different_city_scores_zero(self):
        _, comp = scoring.score_job(
            make_job(worktype="onsite", location="Košice"),
            make_prefs(location="bratislava"), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 0.0)

    def test_onsite_is_a_commute_not_a_region(self):
        # Prague is in Europe and is still not a commute from Bratislava, so
        # the region rule must not leak into the non-remote branch.
        _, comp = scoring.score_job(
            make_job(worktype="onsite", location="Praha", country="CZ"),
            make_prefs(location="bratislava", regions=["EU"]), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 0.0)

    def test_unknown_when_no_user_location(self):
        _, comp = scoring.score_job(
            make_job(worktype="onsite", location="Košice"),
            make_prefs(location=""), WEIGHTS_EQUAL)
        self.assertIsNone(comp["location"])

    def test_unknown_when_nonremote_and_no_job_location(self):
        _, comp = scoring.score_job(
            make_job(worktype="onsite", location=None),
            make_prefs(location="bratislava"), WEIGHTS_EQUAL)
        self.assertIsNone(comp["location"])


class AggregationTests(unittest.TestCase):
    def test_missing_components_do_not_dilute(self):
        # THE invariant: skills fully covered, everything else unparsed.
        # Score must be 100 (skills alone), not 25 (a naive 4-way average).
        score, _ = scoring.score_job(
            make_job(skills="python, react, sql", worktype=None, location=None,
                     seniority=None),
            make_prefs(skills=["python", "react", "sql"]), WEIGHTS_EQUAL)
        self.assertEqual(score, 100.0)

    def test_weighted_combination(self):
        # skills=1.0 (weight 3) + worktype=0.5 (weight 1); others unknown.
        # 100 * (3*1.0 + 1*0.5) / (3 + 1) = 87.5
        weights = {"skills": 3.0, "role": 1.0, "worktype": 1.0,
                   "location": 1.0, "seniority": 1.0}
        score, _ = scoring.score_job(
            make_job(skills="python, react, sql", worktype="hybrid"),
            make_prefs(skills=["python", "react", "sql"], worktype="remote"), weights)
        self.assertEqual(score, 87.5)

    def test_score_is_rounded_to_one_decimal(self):
        score, _ = scoring.score_job(
            make_job(skills="a, b, c"),
            make_prefs(skills=["a"]), WEIGHTS_EQUAL)
        self.assertEqual(score, 33.3)  # 1/3 -> 33.3, not 33.33...

    def test_all_zero_weights_scores_zero(self):
        zero = {"skills": 0.0, "role": 0.0, "worktype": 0.0,
                "location": 0.0, "seniority": 0.0}
        score, _ = scoring.score_job(
            make_job(skills="python"), make_prefs(skills=["python"]), zero)
        self.assertEqual(score, 0.0)


class StrictSeniorityTests(unittest.TestCase):
    def test_strict_mismatch_hard_zeroes_the_score(self):
        score, comp = scoring.score_job(
            make_job(skills="python", seniority="junior"),
            make_prefs(skills=["python"], seniority="senior", seniority_strict=True),
            WEIGHTS_EQUAL)
        self.assertEqual(score, 0.0)
        # Breakdown is still returned so the UI can explain the zero.
        self.assertIn("skills", comp)

    def test_strict_match_scores_normally(self):
        score, _ = scoring.score_job(
            make_job(skills="python, react, sql", seniority="senior"),
            make_prefs(skills=["python", "react", "sql"], seniority="senior",
                       seniority_strict=True),
            WEIGHTS_EQUAL)
        self.assertEqual(score, 100.0)

    def test_strict_does_not_zero_when_job_seniority_unparsed(self):
        # No job seniority -> strict gate can't fire; scored on what's known.
        score, _ = scoring.score_job(
            make_job(skills="python, react, sql", seniority=None),
            make_prefs(skills=["python", "react", "sql"], seniority="senior",
                       seniority_strict=True),
            WEIGHTS_EQUAL)
        self.assertEqual(score, 100.0)


class SkillsEvidenceTests(unittest.TestCase):
    """The floor under the skills denominator (`config.MIN_SKILL_EVIDENCE`).

    Coverage of a one-item list is a claim about one word. Before the floor it
    scored the same 1.0 as covering a full stack, which is how 77 jobs in a
    live pool reached a perfect 100 — a "junior economist" among them, on the
    single word "python" in its description.
    """

    def test_one_detected_skill_cannot_reach_the_top(self):
        _, comp = scoring.score_job(
            make_job(skills="python"), make_prefs(skills=["python"]), WEIGHTS_EQUAL)
        self.assertAlmostEqual(comp["skills"], 1 / 3)

    def test_two_detected_skills_still_rank_below_a_full_stack(self):
        _, comp = scoring.score_job(
            make_job(skills="python, react"),
            make_prefs(skills=["python", "react"]), WEIGHTS_EQUAL)
        self.assertAlmostEqual(comp["skills"], 2 / 3)

    def test_above_the_floor_it_is_plain_coverage(self):
        # Four detected skills, three covered: the floor is not in play at all.
        _, comp = scoring.score_job(
            make_job(skills="python, react, sql, go"),
            make_prefs(skills=["python", "react", "sql"]), WEIGHTS_EQUAL)
        self.assertAlmostEqual(comp["skills"], 3 / 4)

    def test_thin_evidence_still_beats_no_evidence(self):
        # The floor damps a weak match; it must not erase it, or a real
        # one-skill ad would rank with an ad that matched nothing.
        _, thin = scoring.score_job(
            make_job(skills="python"), make_prefs(skills=["python"]), WEIGHTS_EQUAL)
        _, none = scoring.score_job(
            make_job(skills="cobol"), make_prefs(skills=["python"]), WEIGHTS_EQUAL)
        self.assertGreater(thin["skills"], none["skills"])


class RoleComponentTests(unittest.TestCase):
    """What the title says the work is — the component that reads it.

    The ladder is deliberately graded: a search term is written for recall on
    a job board and is a poor precision signal on its own, so the user's own
    skills outrank the discipline they asked for, which outranks a bare
    engineering word that any number of jobs share.
    """

    def prefs(self):
        return make_prefs(skills=["react", "python", "js"],
                          disciplines=["frontend", "backend"])

    def role(self, title):
        _, comp = scoring.score_job(make_job(title=title), self.prefs(), WEIGHTS_EQUAL)
        return comp["role"]

    def test_a_technology_the_user_has_is_the_top_rung(self):
        self.assertEqual(self.role("React Developer"), scoring.ROLE_EXACT)

    def test_their_discipline_is_the_second_rung(self):
        self.assertEqual(self.role("Frontend Developer"), scoring.ROLE_DISCIPLINE)

    def test_some_other_engineering_role_is_the_third(self):
        self.assertEqual(self.role("Network Security Engineer"),
                         scoring.ROLE_GENERIC_HIT)

    def test_a_title_naming_none_of_it_is_a_real_zero(self):
        # Not None. A title about work the user did not ask for is an answer,
        # and this is the job that used to score 100 on one word.
        # Asserted against the literal 0.0 rather than against `ROLE_MISS`,
        # because the constant is the thing under test: comparing it with
        # itself passes just as happily when it is redefined to None.
        self.assertEqual(self.role("Junior ESG Consultant (m/f)"), 0.0)
        self.assertEqual(scoring.ROLE_MISS, 0.0)

    def test_a_miss_drags_the_total_down_instead_of_stepping_aside(self):
        """The whole point, in one assertion: a `None` here would be *excluded*
        from the weighted mean, which is how a "junior ESG consultant" used to
        tie with a React role on a description that mentioned one skill. It is
        a zero, so it counts against the job and the two cannot tie."""
        job = dict(skills="react, python, js", description="React and Python.",
                   worktype="remote", seniority="junior",
                   location="bratislava", country="SK")
        prefs = make_prefs(skills=["react", "python", "js"],
                           disciplines=["frontend"], worktype="remote",
                           seniority="junior", location="bratislava",
                           regions=["SK"])
        dev, _ = scoring.score_job(make_job(title="Junior React Developer", **job),
                                   prefs, WEIGHTS_EQUAL)
        esg, _ = scoring.score_job(make_job(title="Junior ESG Consultant", **job),
                                   prefs, WEIGHTS_EQUAL)
        self.assertEqual(dev, 100.0, "every component matched, including the title")
        self.assertLess(esg, dev)

    def test_a_frontend_role_outranks_a_consultancy_on_the_same_description(self):
        job = dict(skills="python", description="We use Python.")
        weights = {"skills": 1.0, "role": 1.0, "worktype": 1.0,
                   "location": 1.0, "seniority": 1.0}
        dev, _ = scoring.score_job(
            make_job(title="React Developer", **job), self.prefs(), weights)
        other, _ = scoring.score_job(
            make_job(title="Junior ESG Consultant", **job), self.prefs(), weights)
        self.assertGreater(dev, other)

    def test_the_title_is_read_as_words_not_fragments(self):
        # "js" is a skill and a fragment of the Czech "jsou"; "ui" hides inside
        # "building". Neither is this person's job.
        self.assertEqual(self.role("Jsou u nas volna mista"), scoring.ROLE_MISS)
        self.assertEqual(self.role("Building Manager"), scoring.ROLE_MISS)

    def test_slovak_and_czech_titles_inflect(self):
        # "webových" is "web" plus a case ending, and the board posts in Slovak.
        self.assertEqual(self.role("Vyvojar webovych aplikacii"),
                         scoring.ROLE_DISCIPLINE)
        self.assertEqual(self.role("Programatorka do timu"), scoring.ROLE_GENERIC_HIT)

    def test_inflection_does_not_swallow_the_next_word(self):
        # Three trailing letters is a case ending; four is a different word.
        self.assertEqual(self.role("Webinar Host"), scoring.ROLE_MISS)
        self.assertEqual(self.role("Frontline Support Agent"), scoring.ROLE_MISS)

    def test_diacritics_do_not_hide_a_match(self):
        self.assertEqual(self.role("Vývojár webových aplikácií"),
                         scoring.ROLE_DISCIPLINE)

    def test_a_job_with_no_title_leaves_the_component_unknown(self):
        self.assertIsNone(self.role("   "))


class UserDisciplineTests(unittest.TestCase):
    """Which disciplines a user's search terms name (`scoring.user_disciplines`)."""

    def test_terms_name_their_disciplines(self):
        found = scoring.user_disciplines(["react", "frontend", "backend", "tester"])
        self.assertEqual(found, {"frontend", "backend", "qa"})

    def test_a_prefix_a_person_would_actually_type_still_matches(self):
        self.assertIn("frontend", scoring.user_disciplines(["front"]))

    def test_level_words_name_no_discipline(self):
        # THE bug this component was added for: "junior" is the seniority
        # component's word, and counting it here is what floated a "junior ESG
        # consultant" to the top of a frontend developer's list.
        self.assertEqual(scoring.user_disciplines(["junior", "graduate", "student"]),
                         set())

    def test_a_level_word_cannot_smuggle_in_a_discipline(self):
        """The stripping has to happen *before* the prefix test, not merely be
        harmless after it. "trainee" contains "ai", which is one of the words
        `data` is written with — so a person who searched for trainee roles
        would be told they are a data specialist, and every "AI Engineer" in
        the pool would jump a rung. Level words that simply match nothing
        cannot show that; this one can."""
        self.assertIn("trainee", config.ROLE_LEVEL_WORDS)
        self.assertEqual(scoring.user_disciplines(["trainee"]), set())

    def test_diacritics_and_case_do_not_hide_a_term(self):
        self.assertIn("qa", scoring.user_disciplines(["Tester"]))

    def test_nothing_answered_is_no_discipline(self):
        self.assertEqual(scoring.user_disciplines([]), set())
        self.assertEqual(scoring.user_disciplines(None), set())


class OtherProfessionsTests(unittest.TestCase):
    """A title naming another trade is a miss, not a generic hit.

    "Engineer" and "inžinier" earn a rung because on a job board they usually
    mean something — but in Slovakia they are mostly a factory, and a
    *logistics & packaging engineer* collected that rung and cleared a frontend
    developer's threshold at 46.
    """

    def prefs(self):
        return make_prefs(skills=["react", "python"],
                          disciplines=["frontend", "data"])

    def role(self, title):
        _, comp = scoring.score_job(make_job(title=title), self.prefs(), WEIGHTS_EQUAL)
        return comp["role"]

    def test_a_factory_engineer_is_a_miss(self):
        self.assertEqual(self.role("Logistics & Packaging Engineer"), scoring.ROLE_MISS)
        self.assertEqual(self.role("Maintenance Engineer (Robotics)"), scoring.ROLE_MISS)

    def test_a_slovak_production_title_is_a_miss(self):
        self.assertEqual(self.role("Junior procesný inžinier výroby (m/ž)"),
                         scoring.ROLE_MISS)

    def test_a_front_desk_job_is_not_a_frontend_job(self):
        """Why bare "front" is not one of the frontend discipline's words. An
        SPP contact-centre operator matched it on "front office" and sat at 44
        on this list; the user who types "front" still reaches the discipline,
        because `user_disciplines` matches their term to "frontend" by prefix.
        """
        self.assertIn("frontend", scoring.user_disciplines(["front"]))
        self.assertEqual(self.role("Operátor/ka kontaktného centra - front office"),
                         scoring.ROLE_MISS)

    def test_the_vocabulary_is_asked_after_the_rungs_above_it(self):
        """What makes a broad list of other trades safe: a real dev job that
        merely mentions another industry keeps the rung it earned."""
        self.assertEqual(self.role("Frontend Developer for a logistics platform"),
                         scoring.ROLE_DISCIPLINE)
        self.assertEqual(self.role("React developer — warehouse automation"),
                         scoring.ROLE_EXACT)

    def test_a_software_title_still_earns_the_generic_rung(self):
        self.assertEqual(self.role("Software Engineer – GenAI"), scoring.ROLE_GENERIC_HIT)


class TitleLevelTests(unittest.TestCase):
    """The level a title states, read off the title and nowhere else."""

    def test_a_level_above_is_found(self):
        self.assertEqual(scoring.level_floor("Senior React Developer"),
                         scoring.TITLE_LEVELS["senior"])
        self.assertEqual(scoring.level_floor("Tech Lead Frontend"),
                         scoring.TITLE_LEVELS["lead"])
        self.assertEqual(scoring.level_floor("Java Architect"),
                         scoring.TITLE_LEVELS["architect"])

    def test_a_title_naming_no_level_says_nothing(self):
        self.assertIsNone(scoring.level_floor("React Native Developer (iOS)"))
        self.assertIsNone(scoring.level_floor(""))
        self.assertIsNone(scoring.level_floor(None))

    def test_a_range_keeps_its_lowest_rung(self):
        """The reason `level_floor` takes a minimum. "webový manažér (junior -
        senior)" invites a junior by name, and reading only the highest word in
        it would cut an ad addressed to them."""
        levels = scoring.title_levels("webový manažér (junior - senior)")
        self.assertIn(scoring.TITLE_LEVELS["senior"], levels)
        self.assertEqual(scoring.level_floor("webový manažér (junior - senior)"),
                         scoring.TITLE_LEVELS["junior"])

    def test_an_internship_is_the_junior_rung(self):
        for title in ("Software Engineer Intern", "Stážista — backend",
                      "Graduate Developer Programme", "Werkstudent Developer"):
            self.assertEqual(scoring.level_floor(title),
                             scoring.TITLE_LEVELS["junior"], title)

    def test_a_level_word_is_matched_as_a_word(self):
        """"sr" is a level and a fragment of ordinary words; the ladder must not
        find it inside one."""
        self.assertIsNone(scoring.level_floor("Developer for srdce.sk"))


class EligibilityTests(unittest.TestCase):
    """`ineligible` — the three answers that are not low scores.

    Each test also has to refuse to fire on missing data, which is the same
    rule the components follow: a thin row is ranked, never hidden.
    """

    def prefs(self, **kwargs):
        base = dict(skills=["react", "python"], disciplines=["frontend"],
                    location="košice", seniority="junior", regions=["EU"],
                    strict_match=True)
        base.update(kwargs)
        return make_prefs(**base)

    def reason(self, job, prefs=None):
        prefs = prefs or self.prefs()
        _, comp = scoring.score_job(job, prefs, WEIGHTS_EQUAL)
        return comp.get("ineligible")

    def test_another_trade_is_the_wrong_field(self):
        job = make_job(title="Skladník / vodič", location="košice")
        self.assertEqual(self.reason(job), scoring.INELIGIBLE_FIELD)

    def test_a_title_above_your_level_is_cut(self):
        job = make_job(title="Senior React Developer", location="košice")
        self.assertEqual(self.reason(job), scoring.INELIGIBLE_LEVEL)

    def test_your_own_level_is_not_cut(self):
        job = make_job(title="Junior React Developer", location="košice")
        self.assertIsNone(self.reason(job))

    def test_a_level_above_is_only_cut_when_you_said_yours(self):
        job = make_job(title="Senior React Developer", location="košice")
        self.assertIsNone(self.reason(job, self.prefs(seniority="")))

    def test_another_town_in_your_country_is_out_of_reach(self):
        job = make_job(title="React Developer", location="bratislava")
        self.assertEqual(self.reason(job), scoring.INELIGIBLE_REACH)

    def test_the_place_field_outranks_the_prose(self):
        """The bug this rule exists for. Profesia declares no `worktype`, so the
        column is read out of the ad — "možnosť práce z domu" in an ad for an
        office on Bottova 2a stores `remote`, and a perk is not a work permit.
        """
        job = make_job(title="React Developer", location="bottova 2a, bratislava",
                       worktype="remote", country="SK")
        self.assertEqual(self.reason(job), scoring.INELIGIBLE_REACH)

    def test_your_own_town_is_reachable_however_the_place_is_written(self):
        job = make_job(title="React Developer",
                       location="košice, slovakia (job region bratislava and region)")
        self.assertIsNone(self.reason(job))

    def test_a_genuinely_remote_posting_is_judged_on_reach(self):
        here = make_job(title="React Developer", location="práca z domu",
                        worktype="remote", country="SK")
        self.assertIsNone(self.reason(here))
        far = make_job(title="React Developer", location="remote",
                       worktype="remote", country="US")
        self.assertEqual(self.reason(far), scoring.INELIGIBLE_REACH)

    def test_nothing_known_about_the_place_excludes_nothing(self):
        job = make_job(title="React Developer", location=None)
        self.assertIsNone(self.reason(job))
        self.assertIsNone(self.reason(job, self.prefs(location="")))


class StrictMatchTests(unittest.TestCase):
    """The setting that turns eligibility from a note into a cut."""

    def job(self):
        return make_job(title="Senior React Developer", location="bratislava")

    def prefs(self, strict):
        return make_prefs(skills=["react"], disciplines=["frontend"],
                          location="košice", seniority="junior",
                          regions=["EU"], strict_match=strict)

    def test_off_by_default_a_job_is_only_ranked(self):
        score, comp = scoring.score_job(self.job(), self.prefs(False), WEIGHTS_EQUAL)
        self.assertGreater(score, 0)
        self.assertNotIn("ineligible", comp)

    def test_on_it_scores_zero_and_says_why(self):
        score, comp = scoring.score_job(self.job(), self.prefs(True), WEIGHTS_EQUAL)
        self.assertEqual(score, 0.0)
        self.assertEqual(comp["ineligible"], scoring.INELIGIBLE_LEVEL)

    def test_the_breakdown_still_shows_the_components(self):
        """A hidden job must still be explicable: the page that hides it links
        to a detail page that has to say what the job looked like."""
        _, comp = scoring.score_job(self.job(), self.prefs(True), WEIGHTS_EQUAL)
        for name in ("role", "skills", "worktype", "location", "seniority"):
            self.assertIn(name, comp)

    def test_an_eligible_job_is_untouched_by_the_setting(self):
        job = make_job(title="Junior React Developer", location="košice")
        loose, _ = scoring.score_job(job, self.prefs(False), WEIGHTS_EQUAL)
        strict, comp = scoring.score_job(job, self.prefs(True), WEIGHTS_EQUAL)
        self.assertEqual(loose, strict)
        self.assertNotIn("ineligible", comp)


if __name__ == "__main__":
    unittest.main()

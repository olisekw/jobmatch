"""Correctness tests for the weighted match scoring (`jobmatch.scoring`).

The load-bearing invariant (see CLAUDE.md / PROJECT.md) is that scoring runs
over *known* components only — a job whose worktype/seniority never parsed must
not be punished for the missing data. `test_missing_components_do_not_dilute`
is the guard for that; the rest pin the individual component curves, the strict
seniority gate, and the rounding/edge behavior of `score_job`.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import unittest

from jobmatch import places, scoring

WEIGHTS_EQUAL = {"skills": 1.0, "worktype": 1.0, "location": 1.0, "seniority": 1.0}


def make_job(description="Python developer wanted.", skills="",
             worktype=None, location=None, seniority=None, country=None,
             countries=None):
    """A job in the dict shape `score_job` reads (mirrors the DB Row columns).

    `countries` defaults to the packed form of `country`, which is what a
    scanned row holds — pass it explicitly for a posting naming several places.
    """
    return {
        "description": description,
        "skills": skills,
        "worktype": worktype,
        "location": location,
        "seniority": seniority,
        "country": country,
        "countries": countries if countries is not None else places.pack([country]),
    }


def make_prefs(skills=None, worktype=None, location=None,
               seniority=None, seniority_strict=False, regions=None):
    """User prefs in the shape `db.get_user_prefs` returns (skills is a set).

    `regions` is the codes a user picked; `reachable` is the expansion the
    scorer actually tests against, built here by the same `places` call
    `db.get_user_prefs` makes — so a test cannot accidentally assert against a
    set the app would never produce.
    """
    return {
        "skills": set(skills or []),
        "worktype": worktype,
        "location": location,
        "seniority": seniority,
        "seniority_strict": seniority_strict,
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
        score, comp = scoring.score_job(
            make_job(skills="python, react"),
            make_prefs(skills=["python", "react", "go"]), WEIGHTS_EQUAL)
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
            make_job(skills="python", worktype=None, location=None, seniority=None),
            make_prefs(skills=["python"]), WEIGHTS_EQUAL)
        self.assertEqual(score, 100.0)

    def test_weighted_combination(self):
        # skills=1.0 (weight 3) + worktype=0.5 (weight 1); others unknown.
        # 100 * (3*1.0 + 1*0.5) / (3 + 1) = 87.5
        weights = {"skills": 3.0, "worktype": 1.0, "location": 1.0, "seniority": 1.0}
        score, _ = scoring.score_job(
            make_job(skills="python", worktype="hybrid"),
            make_prefs(skills=["python"], worktype="remote"), weights)
        self.assertEqual(score, 87.5)

    def test_score_is_rounded_to_one_decimal(self):
        score, _ = scoring.score_job(
            make_job(skills="a, b, c"),
            make_prefs(skills=["a"]), WEIGHTS_EQUAL)
        self.assertEqual(score, 33.3)  # 1/3 -> 33.3, not 33.33...

    def test_all_zero_weights_scores_zero(self):
        zero = {"skills": 0.0, "worktype": 0.0, "location": 0.0, "seniority": 0.0}
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
            make_job(skills="python", seniority="senior"),
            make_prefs(skills=["python"], seniority="senior", seniority_strict=True),
            WEIGHTS_EQUAL)
        self.assertEqual(score, 100.0)

    def test_strict_does_not_zero_when_job_seniority_unparsed(self):
        # No job seniority -> strict gate can't fire; scored on what's known.
        score, _ = scoring.score_job(
            make_job(skills="python", seniority=None),
            make_prefs(skills=["python"], seniority="senior", seniority_strict=True),
            WEIGHTS_EQUAL)
        self.assertEqual(score, 100.0)


if __name__ == "__main__":
    unittest.main()

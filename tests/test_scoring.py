"""Correctness tests for the weighted match scoring (`jobmatch.scoring`).

The load-bearing invariant (see CLAUDE.md / PROJECT.md) is that scoring runs
over *known* components only — a job whose worktype/seniority never parsed must
not be punished for the missing data. `test_missing_components_do_not_dilute`
is the guard for that; the rest pin the individual component curves, the strict
seniority gate, and the rounding/edge behavior of `score_job`.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import unittest

from jobmatch import scoring

WEIGHTS_EQUAL = {"skills": 1.0, "worktype": 1.0, "location": 1.0, "seniority": 1.0}


def make_job(description="Python developer wanted.", skills="",
             worktype=None, location=None, seniority=None):
    """A job in the dict shape `score_job` reads (mirrors the DB Row columns)."""
    return {
        "description": description,
        "skills": skills,
        "worktype": worktype,
        "location": location,
        "seniority": seniority,
    }


def make_prefs(skills=None, worktype=None, location=None,
               seniority=None, seniority_strict=False):
    """User prefs in the shape `db.get_user_prefs` returns (skills is a set)."""
    return {
        "skills": set(skills or []),
        "worktype": worktype,
        "location": location,
        "seniority": seniority,
        "seniority_strict": seniority_strict,
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
    def test_remote_job_is_full_location_score(self):
        _, comp = scoring.score_job(
            make_job(worktype="remote", location=None),
            make_prefs(location="bratislava"), WEIGHTS_EQUAL)
        self.assertEqual(comp["location"], 1.0)

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

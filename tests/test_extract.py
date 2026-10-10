"""Correctness tests for regex field extraction (`jobmatch.extract`).

Covers skill detection, the category extractors (worktype / seniority /
employment type), and the *priority* rules that resolve a description matching
several categories at once ("senior role, juniors welcome" is a senior ad).

Writing this suite surfaced two real bugs, both now fixed in `config.py`: the
patterns matched only undeclined, partly mis-spelled Slovak ("práca z domu",
"úvazok"), so the everyday phrasings "ponúkame prácu z domu" and "plný úväzok"
were missed. The declension tests below are the regression guards for that.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import unittest

from jobmatch import extract


class SkillExtractionTests(unittest.TestCase):
    def test_finds_known_stack_case_insensitively(self):
        skills = extract.extract_skills("We use Python, React and TypeScript daily")
        self.assertIn("python", skills)
        self.assertIn("react", skills)
        self.assertIn("typescript", skills)

    def test_result_is_sorted_and_deduped(self):
        skills = extract.extract_skills("python PYTHON Python react")
        self.assertEqual(skills, ["python", "react"])

    def test_short_tokens_go_and_c_survive_the_length_guard(self):
        skills = extract.extract_skills("Go and C, plus C++ and C#")
        for token in ("go", "c", "c++", "c#"):
            self.assertIn(token, skills)

    def test_js_abbreviation_is_detected(self):
        self.assertIn("js", extract.extract_skills("Strong JS fundamentals"))

    def test_non_technical_text_yields_no_skills(self):
        self.assertEqual(extract.extract_skills("We sell insurance to families"), [])

    def test_empty_or_non_string_is_empty(self):
        self.assertEqual(extract.extract_skills(""), [])
        self.assertEqual(extract.extract_skills(None), [])

    def test_postgresql_currently_yields_both_tokens(self):
        # Characterization test (documents actual behavior, not the ideal):
        # "PostgreSQL" matches both the `postgres` and `postgresql` patterns, so
        # both tokens come back. Ideally this would collapse to one canonical
        # token; kept as a known quirk so a future de-dupe change is intentional.
        self.assertEqual(extract.extract_skills("PostgreSQL"), ["postgres", "postgresql"])


class WorktypeExtractionTests(unittest.TestCase):
    def test_english_home_office_is_remote(self):
        self.assertEqual(extract.extract_worktype("Fully home office role"), "remote")

    def test_slovak_praca_z_domu_is_remote(self):
        self.assertEqual(extract.extract_worktype("Ponúkame prácu na diaľku, práca z domu"),
                         "remote")

    def test_remote_survives_slovak_case_endings(self):
        # Regression: "práca" is declined in real ads ("ponúkame prácu z domu"),
        # which the original undeclined patterns missed entirely.
        for text in ("Ponúkame prácu z domu", "prácou z domu", "prácu na diaľku"):
            self.assertEqual(extract.extract_worktype(text), "remote", text)

    def test_onsite_survives_slovak_case_endings(self):
        for text in ("Ponúkame prácu v kancelárii", "prácu na mieste"):
            self.assertEqual(extract.extract_worktype(text), "onsite", text)

    def test_slovak_onsite(self):
        self.assertEqual(extract.extract_worktype("Práca v kancelárii v centre mesta"),
                         "onsite")

    def test_remote_wins_over_onsite_by_priority(self):
        # A mixed ad resolves to the most-flexible worktype named.
        self.assertEqual(
            extract.extract_worktype("Mostly remote, occasionally onsite for workshops"),
            "remote")

    def test_partial_work_from_home_is_hybrid_not_remote(self):
        # Regression: these all contain "prác… z domu", so they used to resolve to
        # fully remote — and a remote job also collects a full location score.
        for text in ("SAP programátor, 50% práce z domu",
                     "Flexibilný čas s možnosťou čiastočne práce z domu",
                     "Pozícia umožňuje občasnú prácu z domu",
                     "Je možná aj kombinácia s prácou z domu",
                     "2 dni v týždni z domu"):
            self.assertEqual(extract.extract_worktype(text), "hybrid", text)

    def test_unqualified_work_from_home_stays_remote(self):
        # The counterpart: no partial qualifier -> still fully remote. Bare
        # "možnosť práce z domu" is deliberately left as remote.
        for text in ("Miesto práce: Práca z domu", "Ponúkame prácu z domu",
                     "možnosť práce z domu"):
            self.assertEqual(extract.extract_worktype(text), "remote", text)

    def test_hybrid_wins_over_remote_by_priority(self):
        # A hybrid marker anywhere beats a bare remote mention.
        self.assertEqual(
            extract.extract_worktype("Home office, hybridný režim, 2-3 dni v office"),
            "hybrid")

    def test_no_worktype_signal_is_none(self):
        self.assertIsNone(extract.extract_worktype("Great team and free coffee"))


class SeniorityExtractionTests(unittest.TestCase):
    def test_plain_junior(self):
        self.assertEqual(extract.extract_seniority("Junior developer, entry level"),
                         "junior")

    def test_highest_level_named_wins(self):
        # "senior ... juniors welcome" is still a senior ad.
        self.assertEqual(extract.extract_seniority("Senior engineer; juniors welcome"),
                         "senior")

    def test_no_seniority_signal_is_none(self):
        self.assertIsNone(extract.extract_seniority("We build web apps"))


class ExperienceYearsExtractionTests(unittest.TestCase):
    def test_plus_form(self):
        self.assertEqual(
            extract.extract_experience_years("We need 5+ years of experience"), 5)

    def test_minimum_qualifier(self):
        self.assertEqual(
            extract.extract_experience_years("Minimum 5 years of experience required"), 5)

    def test_at_least_qualifier(self):
        self.assertEqual(
            extract.extract_experience_years("At least 3 years experience in Python"), 3)

    def test_range_takes_the_lower_bound(self):
        # "3-5 years" states a minimum of 3, not an upper bound of 5.
        self.assertEqual(
            extract.extract_experience_years("3-5 years of experience wanted"), 3)

    def test_highest_figure_named_wins(self):
        self.assertEqual(
            extract.extract_experience_years(
                "2+ years is fine, but ideally 5+ years of commercial experience"), 5)

    def test_slovak_minimalne_rokov_praxe(self):
        self.assertEqual(
            extract.extract_experience_years("minimálne 5 rokov praxe"), 5)

    def test_slovak_rokov_skusenosti(self):
        self.assertEqual(
            extract.extract_experience_years("5 rokov skúseností v odbore"), 5)

    def test_slovak_min_roky_praxe(self):
        self.assertEqual(extract.extract_experience_years("min. 3 roky praxe"), 3)

    def test_czech_alespon_roky_zkusenosti(self):
        self.assertEqual(
            extract.extract_experience_years("zkušenosti alespoň 4 roky"), 4)

    def test_czech_min_roky_zkusenosti(self):
        self.assertEqual(
            extract.extract_experience_years("min. 4 roky zkušeností"), 4)

    def test_salary_figure_is_not_a_years_figure(self):
        self.assertIsNone(extract.extract_experience_years("Salary 5000 EUR gross"))

    def test_experience_with_a_technology_is_not_a_years_figure(self):
        self.assertIsNone(
            extract.extract_experience_years("Experience with Docker and Kubernetes"))

    def test_no_signal_is_none(self):
        self.assertIsNone(extract.extract_experience_years("We build web apps"))


class EmploymentTypeExtractionTests(unittest.TestCase):
    def test_english_fulltime(self):
        self.assertEqual(extract.extract_employment_type("This is a full time position"),
                         "fulltime")

    def test_slovak_hpp_is_fulltime(self):
        self.assertEqual(extract.extract_employment_type("Nástup na HPP"), "fulltime")

    def test_internship_priority_over_fulltime(self):
        # An internship that also says "full time" resolves to internship.
        self.assertEqual(
            extract.extract_employment_type("Full-time internship / stáž for students"),
            "internship")

    def test_no_signal_is_none(self):
        self.assertIsNone(extract.extract_employment_type("Nice office in the centre"))

    def test_slovak_plny_uvazok_is_fulltime(self):
        # Regression: the patterns used to match only "úvazok", missing the real
        # Slovak spelling "úväzok" (with ä) — the most common full-time phrasing
        # on SK boards. Both spellings must work.
        self.assertEqual(extract.extract_employment_type("Ponúkame plný úväzok"),
                         "fulltime")
        self.assertEqual(extract.extract_employment_type("plny uvazok"), "fulltime")

    def test_fulltime_survives_slovak_case_endings(self):
        # Ads decline the phrase: "na plnom úväzku", "plného úväzku".
        for text in ("Nástup na plnom úväzku", "Práca na plného úväzku",
                     "100% úväzok", "plným úväzkom"):
            self.assertEqual(extract.extract_employment_type(text), "fulltime", text)

    def test_slovak_ciastocny_uvazok_is_parttime(self):
        # Same ä bug on the part-time side; must not leak into "fulltime".
        for text in ("čiastočný úväzok", "na čiastočnom úväzku", "polovičný úväzok",
                     "20-hodinový úväzok"):
            self.assertEqual(extract.extract_employment_type(text), "parttime", text)


class ExtractAllTests(unittest.TestCase):
    def test_bundles_all_fields(self):
        result = extract.extract_all("Senior Python developer, home office")
        self.assertEqual(result["skills"], "python")
        self.assertEqual(result["worktype"], "remote")
        self.assertEqual(result["seniority"], "senior")
        # employment_type not stated -> None
        self.assertIsNone(result["employment_type"])

    def test_skills_field_is_comma_joined(self):
        result = extract.extract_all("We use Python and Django")
        self.assertEqual(result["skills"], "django, python")  # sorted, ", "-joined


if __name__ == "__main__":
    unittest.main()

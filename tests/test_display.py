"""Display formatting: the strings the UI actually shows a person."""

import unittest
from datetime import datetime

from jobmatch import display


class TestLabels(unittest.TestCase):
    def test_known_values_get_their_friendly_name(self):
        self.assertEqual(display.label(display.SENIORITY, "medior"), "Mid-level")
        self.assertEqual(display.label(display.WORKTYPE, "onsite"), "On-site")
        self.assertEqual(display.label(display.EMPLOYMENT_TYPE, "fulltime"), "Full-time")
        self.assertEqual(
            display.label(display.APPLICATION_STATUS, "no_response"), "No response"
        )

    def test_unknown_value_still_reads_as_words(self):
        """A category a future extractor invents must not surface raw."""
        self.assertEqual(display.label(display.EMPLOYMENT_TYPE, "contract"), "Contract")
        self.assertEqual(display.label(display.APPLICATION_STATUS, "on_hold"), "On hold")

    def test_missing_value_is_empty(self):
        for value in (None, "", 0):
            self.assertEqual(display.label(display.WORKTYPE, value), "")

    def test_options_pairs_values_with_labels(self):
        self.assertIn(
            {"value": "remote", "label": "Remote"}, display.options(display.WORKTYPE)
        )


class TestScoreComponents(unittest.TestCase):
    """The five components are named once, and everything else reads that list.

    They used to be written out in `app.js`, in the Settings sliders and in the
    landing page's prose, which is how the landing page came to describe four
    components months after there were five.
    """

    def test_the_weight_keys_are_exactly_the_ones_the_route_normalizes(self):
        import app

        self.assertEqual(
            {c["weight_key"] for c in display.score_components()},
            set(app.WEIGHT_KEYS),
            "a component whose weight the PUT does not normalize, or the reverse",
        )

    def test_every_component_has_a_word_for_itself(self):
        for c in display.score_components():
            self.assertTrue(c["label"], f"{c['key']} has no label")
            self.assertTrue(c["key"])

    def test_the_order_is_the_one_the_bars_are_drawn_in(self):
        # Role first: it is the component known for every scored job, so it is
        # the one a reader should meet before the four that can be unknown.
        self.assertEqual(display.score_components()[0]["key"], "role")

    def test_the_weight_messages_are_derived_from_the_same_names(self):
        # `WEIGHT` is what a validation error calls a weight. Deriving it is what
        # stops "Worktype" and "The worktype weight" drifting apart.
        self.assertEqual(display.WEIGHT["weight_skill"], "The skills weight")
        self.assertEqual(
            set(display.WEIGHT), {c["weight_key"] for c in display.score_components()}
        )


class TestJobSort(unittest.TestCase):
    def test_every_ordering_the_server_can_run_has_a_name(self):
        from jobmatch import db

        self.assertEqual(
            set(display.JOB_SORT), set(db.JOB_ORDER),
            "the Sort dropdown is built from these, so an unnamed ordering is "
            "unreachable and a named one the server cannot run is a 500",
        )


class TestRelativeDate(unittest.TestCase):
    TODAY = datetime(2026, 8, 11).date()

    def rel(self, iso):
        return display.relative_date(iso, today=self.TODAY)

    def test_recent_days_read_as_words(self):
        self.assertEqual(self.rel("2026-08-11"), "today")
        self.assertEqual(self.rel("2026-08-10"), "yesterday")
        self.assertEqual(self.rel("2026-08-08"), "3 days ago")
        self.assertEqual(self.rel("2026-08-06"), "5 days ago")

    def test_the_day_count_survives_past_a_week(self):
        """A job board's ages are read in days; "last week" hid the digit."""
        self.assertEqual(self.rel("2026-08-04"), "7 days ago")
        self.assertEqual(self.rel("2026-08-03"), "8 days ago")
        self.assertEqual(self.rel("2026-07-28"), "14 days ago")

    def test_past_a_month_a_date_is_the_shorter_sentence(self):
        self.assertEqual(self.rel("2026-07-11"), "31 days ago")
        self.assertEqual(self.rel("2026-07-10"), "10 Jul")
        self.assertEqual(self.rel("2026-06-12"), "12 Jun")

    def test_another_year_carries_the_year(self):
        self.assertEqual(self.rel("2025-07-12"), "12 Jul 2025")

    def test_a_timestamp_is_accepted_where_a_date_is_expected(self):
        self.assertEqual(self.rel("2026-08-10 22:14:03"), "yesterday")

    def test_future_dates_do_not_produce_negative_ages(self):
        """Boards do post ahead; "in -2 days" would be worse than a date."""
        self.assertEqual(self.rel("2026-08-13"), "13 Aug")

    def test_unusable_input_is_empty(self):
        for value in (None, "", "not a date", 20260811):
            self.assertEqual(self.rel(value), "")


class TestRelativeTime(unittest.TestCase):
    NOW = datetime(2026, 8, 11, 14, 30, 0)

    def rel(self, iso):
        return display.relative_time(iso, now=self.NOW)

    def test_within_the_hour(self):
        self.assertEqual(self.rel("2026-08-11 14:29:30"), "just now")
        self.assertEqual(self.rel("2026-08-11 14:25:00"), "5 minutes ago")
        self.assertEqual(self.rel("2026-08-11 13:45:00"), "45 minutes ago")

    def test_within_the_day(self):
        self.assertEqual(self.rel("2026-08-11 13:20:00"), "an hour ago")
        self.assertEqual(self.rel("2026-08-11 06:50:00"), "7 hours ago")

    def test_past_a_day_it_hands_over_to_relative_date(self):
        self.assertEqual(self.rel("2026-08-09 06:50:00"), "2 days ago")
        self.assertEqual(self.rel("2026-06-09 06:50:00"), "9 Jun")

    def test_a_clock_ahead_of_the_server_reads_as_just_now(self):
        self.assertEqual(self.rel("2026-08-11 14:31:00"), "just now")

    def test_unusable_input_is_empty(self):
        self.assertEqual(self.rel(None), "")
        self.assertEqual(self.rel("whenever"), "")


class TestExactTime(unittest.TestCase):
    def test_timestamps_keep_their_time_and_say_which_zone(self):
        self.assertEqual(
            display.exact_time("2026-08-08 06:50:12"), "8 Aug 2026, 06:50 UTC"
        )

    def test_date_only_columns_do_not_invent_a_midnight(self):
        self.assertEqual(display.exact_time("2026-08-08"), "8 Aug 2026")

    def test_unusable_input_is_empty(self):
        self.assertEqual(display.exact_time(None), "")


if __name__ == "__main__":
    unittest.main()

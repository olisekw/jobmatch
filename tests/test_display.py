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


class TestRelativeDate(unittest.TestCase):
    TODAY = datetime(2026, 8, 11).date()

    def rel(self, iso):
        return display.relative_date(iso, today=self.TODAY)

    def test_recent_days_read_as_words(self):
        self.assertEqual(self.rel("2026-08-11"), "today")
        self.assertEqual(self.rel("2026-08-10"), "yesterday")
        self.assertEqual(self.rel("2026-08-08"), "3 days ago")
        self.assertEqual(self.rel("2026-08-06"), "5 days ago")

    def test_a_week_or_more_falls_back_to_a_date(self):
        self.assertEqual(self.rel("2026-08-04"), "last week")
        self.assertEqual(self.rel("2026-07-12"), "12 Jul")

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

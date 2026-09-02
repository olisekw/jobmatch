"""Freshness → posting date, for the two languages the boards write in.

jobs.cz brought Czech into this parser. Most of it was already there, because
Slovak and Czech share the words that matter ("dnes", "včera"), but three
things are the board's own: `před` where Slovak writes `pred`, its own week
and month nouns, and a date with a genitive month name and **no year at all**
("24. srpna") — a job board never prints one.

The case worth naming is the last test. jobs.cz shows an ad's *expiry*
countdown in the same element it shows its posting date in, so reading one as
the other would date a job by its deadline: "Končí za 3 dny" is not three days
old, it is three days from dying, and the two point opposite ways in time.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import unittest

from jobmatch import dates

TODAY = "2026-08-28"


class SlovakTests(unittest.TestCase):
    """The phrases that were already parsed, so the Czech ones cannot cost them."""

    def test_the_profesia_relative_phrases(self):
        cases = {
            "pred 2 dňami": "2026-08-26", "pred hodinou": TODAY,
            "dnes": TODAY, "včera": "2026-08-27", "pred týždňom": "2026-08-21",
            "pred mesiacom": "2026-07-29", "pred 3 týždňami": "2026-08-07",
        }
        for text, expected in cases.items():
            self.assertEqual(dates.parse_posted(text, TODAY), expected, text)

    def test_the_kariera_absolute_date(self):
        self.assertEqual(dates.parse_posted("13.07.2026", TODAY), "2026-07-13")


class CzechTests(unittest.TestCase):
    def test_the_year_less_date_jobs_cz_prints(self):
        self.assertEqual(dates.parse_posted("24. srpna", TODAY), "2026-08-24")
        self.assertEqual(dates.parse_posted("1. ledna", TODAY), "2026-01-01")

    def test_a_date_that_would_be_in_the_future_belongs_to_last_year(self):
        """No year on the page, and a board does not advertise jobs it has not listed."""
        self.assertEqual(dates.parse_posted("29. srpna", TODAY), "2025-08-29")
        self.assertEqual(dates.parse_posted("15. prosince", TODAY), "2025-12-15")

    def test_every_month_name_is_understood(self):
        for month in dates._CZECH_MONTHS:
            self.assertIsNotNone(dates.parse_posted(f"5. {month}", TODAY), month)

    def test_the_relative_phrases(self):
        cases = {
            "Přidáno dnes": TODAY, "Přidáno včera": "2026-08-27",
            "Přidáno před hodinou": TODAY, "před 3 dny": "2026-08-25",
            "před týdnem": "2026-08-21", "před 2 týdny": "2026-08-14",
            "před měsícem": "2026-07-29", "Aktualizováno dnes": TODAY,
        }
        for text, expected in cases.items():
            self.assertEqual(dates.parse_posted(text, TODAY), expected, text)


class ExpiryTests(unittest.TestCase):
    def test_an_expiry_countdown_is_not_a_posting_date(self):
        for text in ("Končí za 8 hodin", "Končí za 3 dny", "Končí zítra", "Končí dnes"):
            self.assertIsNone(dates.parse_posted(text, TODAY),
                              f"{text!r} says when the ad dies, not when it was born")

    def test_nothing_at_all_is_none_rather_than_today(self):
        for text in (None, "", "   ", "Odpověď do 2 týdnů", 17):
            self.assertIsNone(dates.parse_posted(text, TODAY), repr(text))


if __name__ == "__main__":
    unittest.main()

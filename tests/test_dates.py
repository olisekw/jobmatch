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
from datetime import date

from jobmatch import dates, display

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


class AgeIsDerivedNotFrozenTests(unittest.TestCase):
    """A posting gets older while it sits in the pool, and must read that way.

    `jobs.posted_at` is the absolute date a board's freshness string resolved
    to, written once by the scan that found the row. Nothing downstream stores
    an age: `days_ago` and `display.relative_date` both subtract from *today*,
    which is the only arrangement in which one stored row answers the question
    correctly on every later day. Storing the age instead — "4 days ago",
    straight off the board — would have pinned the row to the scan that found
    it, and the whole pool would read as though it were scraped this morning.
    """

    SCRAPED = "2026-10-03"     # the day the scan ran
    LATER = date(2026, 10, 7)  # four days on, reading the same row

    def stored(self, freshness):
        """What the scan of 3 Oct would have written into `jobs.posted_at`."""
        return dates.parse_posted(freshness, self.SCRAPED)

    def test_the_boards_words_resolve_against_the_day_of_the_scan(self):
        self.assertEqual(self.stored("pred 4 dňami"), "2026-09-29")
        self.assertEqual(self.stored("dnes"), self.SCRAPED)

    def test_four_days_old_on_the_scan_is_eight_days_old_four_days_later(self):
        posted = self.stored("pred 4 dňami")
        self.assertEqual(dates.days_ago(posted, date.fromisoformat(self.SCRAPED)), 4)
        self.assertEqual(dates.days_ago(posted, self.LATER), 8)

    def test_the_words_on_the_card_move_with_it(self):
        """The same row, read on two days, through the payload's own helper."""
        posted = self.stored("pred 4 dňami")
        self.assertEqual(
            display.relative_date(posted, today=date.fromisoformat(self.SCRAPED)),
            "4 days ago")
        self.assertEqual(display.relative_date(posted, today=self.LATER),
                         "8 days ago")

    def test_todays_posting_is_not_still_today_a_week_later(self):
        posted = self.stored("dnes")
        self.assertEqual(display.relative_date(
            posted, today=date.fromisoformat(self.SCRAPED)), "today")
        self.assertEqual(display.relative_date(posted, today=self.LATER),
                         "4 days ago")

    def test_an_unparseable_freshness_stores_nothing_rather_than_today(self):
        """A date we could not read must not become a posting dated now.

        `parse_posted` returning None is what keeps the row out of every
        freshness window, instead of it claiming the day of the scan.
        """
        self.assertIsNone(self.stored("Nástup dohodou"))
        self.assertIsNone(dates.days_ago(None))
        self.assertEqual(display.relative_date(None), "")


if __name__ == "__main__":
    unittest.main()

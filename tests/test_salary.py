"""Salary parsing, and the one number two postings can be compared by.

Two questions, one table. **What unit is a bare number in?** The board writes
"70 000 – 85 000 Kč" and never says over what period, so the period is guessed
from magnitude — a guess that was written in euros and applied to every
currency, which made an ordinary Czech monthly wage look like a yearly one.
**And what is that number worth?** The derived rate the pay filter selects on
and the "Best pay" sort orders by was per *hour* but in each job's own money,
so 140 000 Kč and 140 000 € ranked the same. Both are asked of `EUR_RATES`,
because both are the same fact about a currency: how big a number in it is.

jobs.cz is the board that brought a non-euro-scaled currency into the pool,
which is where both surfaced.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import unittest

from jobmatch import salary


class PeriodGuessTests(unittest.TestCase):
    def test_a_czech_monthly_wage_is_monthly(self):
        for text in ("70 000 – 85 000 Kč", "140 000 – 180 000 Kč", "42 000 Kč"):
            self.assertEqual(salary.parse_salary(text)[3], "month", text)

    def test_a_czech_yearly_salary_is_still_yearly(self):
        self.assertEqual(salary.parse_salary("1 200 000 Kč")[3], "year")

    def test_a_czech_hourly_rate_is_still_hourly(self):
        self.assertEqual(salary.parse_salary("350 Kč")[3], "hour")

    def test_a_polish_monthly_wage_is_monthly(self):
        self.assertEqual(salary.parse_salary("15 000 zł")[3], "month")

    def test_the_euro_scaled_currencies_are_untouched(self):
        """The scale table must not move any answer that was already right."""
        cases = [
            ("900 - 1 000 eur/mesiac", "month"), ("8,50 eur/hod", "hour"),
            ("$70k - $90k", "year"), ("70000-90000 USD/year", "year"),
            ("2 500 – 4 500 EUR", "month"), ("150 EUR", "hour"),
            ("£45000", "year"), ("120 CHF", "hour"),
        ]
        for text, expected in cases:
            self.assertEqual(salary.parse_salary(text)[3], expected, text)

    def test_a_stated_period_always_beats_the_guess(self):
        """The guess only ever fills a gap; it never overrules the board."""
        self.assertEqual(salary.parse_salary("85 000 Kč / rok")[3], "year")
        self.assertEqual(salary.parse_salary("350 Kč/hod")[3], "hour")

    def test_no_currency_means_no_guess_at_all(self):
        self.assertEqual(salary.parse_salary("70 000 - 85 000"), (None, None, None, None))

    def test_the_amount_and_currency_are_never_converted(self):
        """No FX, and this change does not sneak any in — only the unit moved."""
        low, high, currency, period = salary.parse_salary("70 000 – 85 000 Kč")
        self.assertEqual((low, high, currency), (70000.0, 85000.0, "CZK"))
        self.assertEqual(period, "month")


class HourlyDerivationTests(unittest.TestCase):
    def test_the_czech_wage_derives_a_sane_rate_in_euros(self):
        """160 hours of an 85 000 Kč month is about €22, not about 531."""
        low, high, currency, period = salary.parse_salary("70 000 – 85 000 Kč")
        self.assertEqual(salary.hourly_eur(low, high, period, currency),
                         (18.1, 22.0))

    def test_a_period_alone_never_made_two_currencies_comparable(self):
        """The bug, stated as an assertion: same number, different money."""
        czk = salary.hourly_eur(None, 140000, "month", "CZK")[1]
        eur = salary.hourly_eur(None, 140000, "month", "EUR")[1]
        self.assertLess(czk, eur / 20)

    def test_a_currency_with_no_rate_is_unknown_rather_than_par(self):
        """Reading it at par would print euros for a wage nobody quoted."""
        self.assertEqual(salary.hourly_eur(1000, 2000, "month", "SEK"),
                         (None, None))
        self.assertEqual(salary.hourly_eur(1000, 2000, "month", None),
                         (None, None))

    def test_an_unknown_period_is_still_unknown(self):
        self.assertEqual(salary.hourly_eur(1000, 2000, None, "EUR"),
                         (None, None))

    def test_the_parser_and_the_rate_table_cover_each_other(self):
        """Neither half may name a currency the other has never heard of.

        A rate for a currency `_CURRENCIES` cannot produce is dead code; a
        currency it *can* produce with no rate is worse — those jobs quietly
        leave the pay filter and the sort with nothing said about it.
        """
        producible = set()
        for text in ("1 Kč", "1 zł", "1 EUR", "1 USD", "1 GBP", "1 CHF"):
            producible.add(salary.parse_salary(text + "/hod")[2])
        self.assertEqual(set(salary.EUR_RATES), producible)

    def test_the_comparison_currency_has_a_rate_of_one(self):
        """Anything else and every euro job is converted out of itself."""
        self.assertEqual(salary.EUR_RATES[salary.COMPARISON_CURRENCY], 1.0)


class DisplayTests(unittest.TestCase):
    def test_the_range_keeps_the_boards_money_and_the_rate_is_in_euros(self):
        """Both on one card: the posting's claim, and our comparison of it."""
        self.assertEqual(
            salary.range_display(70000, 85000, "CZK", "month"),
            "70\u202f000\u201385\u202f000 Kč/mo")
        self.assertEqual(
            salary.hourly_display(70000, 85000, "CZK", "month"),
            "≈ 18.1–22 €/h")

    def test_a_converted_figure_says_what_it_was_converted_at(self):
        note = salary.conversion_note("CZK")
        self.assertIn("24.15", note)
        self.assertIn(salary.RATES_AS_OF, note)

    def test_a_euro_job_was_not_converted_and_does_not_claim_to_be(self):
        self.assertIsNone(salary.conversion_note("EUR"))
        self.assertIsNone(salary.conversion_note(None))
        self.assertIsNone(salary.conversion_note("SEK"))

    def test_a_job_we_cannot_compare_prints_no_rate_at_all(self):
        self.assertIsNone(salary.hourly_display(1000, 2000, "SEK", "month"))


if __name__ == "__main__":
    unittest.main()

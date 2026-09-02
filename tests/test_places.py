"""Tests for `jobmatch.places` — board text → one country code.

The point of this module is that `jobs.country` is *stored*, so a wrong guess
here is a wrong chip on a card and a job missing from a filter until somebody
re-runs the backfill. These tests pin the three rules the docstring promises:
specific beats general, the board is only ever a fallback, and a row nothing
places stays None rather than being guessed into a country.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import unittest

from jobmatch import places


class CountryTests(unittest.TestCase):
    def test_a_slovak_town_is_slovakia_however_it_is_spelled(self):
        for text in ("Bratislava", "KOŠICE", "Žilina - okres Žilina", "banská bystrica"):
            self.assertEqual(places.country("profesia", text), "SK", text)

    def test_a_country_name_beats_the_board_it_came_from(self):
        """profesia lists Slovak jobs — except when it says otherwise."""
        self.assertEqual(places.country("profesia", "Praha (hlavní město Praha)"), "CZ")
        self.assertEqual(places.country("kariera", "Wien, Rakúsko"), "AT")

    def test_an_unrecognised_slovak_town_still_lands_in_slovakia(self):
        """The fallback is the board, and these two only ever list one country."""
        self.assertEqual(places.country("profesia", "Vranov nad Topľou"), "SK")
        self.assertEqual(places.country("kariera", "Stupava"), "SK")

    def test_the_remote_boards_name_countries_and_regions(self):
        cases = {
            "USA only": "US",
            "United States": "US",
            "Berlin, Germany": "DE",
            "EMEA": "EU",
            "Anywhere in Europe": "EU",  # a region wins over "anywhere"
            "LATAM": "LATAM",
            "India": "IN",
            "Worldwide": "ANY",
            "Anywhere": "ANY",
            "remote": "ANY",
        }
        for text, expected in cases.items():
            self.assertEqual(places.country("remoteok", text), expected, text)

    def test_a_board_with_no_default_leaves_an_unplaceable_job_unplaced(self):
        """None is a real answer: the card falls back to the board's own text."""
        self.assertIsNone(places.country("remoteok", ""))
        self.assertIsNone(places.country("remotive", "Contact us for details"))
        self.assertIsNone(places.country(None, None))


class LabelTests(unittest.TestCase):
    def test_every_code_the_tables_can_return_has_a_label(self):
        """A code with no label would reach the UI as 'LATAM' in a chip."""
        codes = {code for table in (places._COUNTRIES, places._CITIES, places._REGIONS)
                 for code, _ in table}
        codes.update(places.REGIONS)
        codes.update(places.SOURCE_DEFAULT.values())
        self.assertEqual(codes - set(places.LABELS), set())

    def test_a_missing_code_reads_as_nothing_rather_than_as_none(self):
        self.assertEqual(places.label(None), "")
        self.assertEqual(places.label(""), "")


class OptionTests(unittest.TestCase):
    def test_regions_come_first_and_countries_alphabetically(self):
        options = places.options(["US", "SK", "ANY", "DE", "EU"])
        self.assertEqual([o["value"] for o in options], ["ANY", "EU", "DE", "SK", "US"])
        self.assertEqual(options[0]["label"], "Worldwide")

    def test_only_what_the_pool_holds_is_offered_and_never_twice(self):
        """A dropdown of forty countries that match nothing is worse than none."""
        options = places.options(["SK", "SK", None, "SK"])
        self.assertEqual(options, [{"value": "SK", "label": "Slovakia"}])


class ReachabilityTests(unittest.TestCase):
    """"Where I can work" → every `jobs.country` value that satisfies it.

    One expansion, read by the scorer and by the Jobs filter, so these are the
    tests that stop the list and the score disagreeing about which countries a
    person can take a job in.
    """

    def test_a_region_covers_the_countries_inside_it(self):
        codes = places.reachable_codes(["EU"])
        for code in ("DE", "PT", "SK", "IE"):
            self.assertIn(code, codes)

    def test_a_country_is_covered_by_its_own_region(self):
        # Somebody who can only work in Slovakia is still served by a posting
        # addressed to Europe as a whole.
        self.assertIn("EU", places.reachable_codes(["SK"]))

    def test_regions_do_not_bleed_into_each_other(self):
        codes = places.reachable_codes(["SK"])
        for code in ("US", "CA", "NA", "IN", "APAC", "BR"):
            self.assertNotIn(code, codes)

    def test_worldwide_postings_reach_everybody(self):
        self.assertIn("ANY", places.reachable_codes(["SK"]))
        self.assertIn("ANY", places.reachable_codes(["JP"]))

    def test_worldwide_as_a_preference_reaches_everywhere(self):
        # The rare user who really can work anywhere, and says so — as opposed
        # to the default, which must never mean this (it was the bug).
        self.assertEqual(places.reachable_codes(["ANY"]), set(places.LABELS))

    def test_nothing_asked_expands_to_nothing(self):
        # Empty is "unknown", which callers turn into a hatched bar and an
        # ignored filter — never into "nowhere is reachable".
        self.assertEqual(places.reachable_codes([]), set())
        self.assertEqual(places.reachable_codes(None), set())

    def test_codes_nobody_knows_are_dropped(self):
        self.assertEqual(places.reachable_codes(["XX", "ZZ"]), set())
        self.assertIn("SK", places.reachable_codes(["SK", "XX"]))

    def test_north_america_is_the_hiring_pool_the_boards_mean(self):
        codes = places.reachable_codes(["NA"])
        self.assertIn("US", codes)
        self.assertIn("CA", codes)
        self.assertNotIn("MX", codes)


class DefaultRegionTests(unittest.TestCase):
    def test_a_home_country_brings_its_region_with_it(self):
        self.assertEqual(places.default_regions("SK"), {"SK", "EU"})

    def test_the_default_is_not_europe_for_everybody(self):
        self.assertEqual(places.default_regions("CA"), {"CA", "NA"})

    def test_a_country_in_no_region_is_just_itself(self):
        self.assertEqual(places.default_regions("IL"), {"IL"})

    def test_nothing_in_nothing_out(self):
        # Which is what keeps the location component unknown for a user who
        # has told us neither a town nor a set of places.
        self.assertEqual(places.default_regions(None), set())
        self.assertEqual(places.default_regions("XX"), set())


class WorkOptionTests(unittest.TestCase):
    def test_every_region_is_offered_whatever_the_pool_holds(self):
        values = [o["value"] for o in places.work_options([])]
        self.assertEqual(values[:len(places.REGIONS)], list(places.REGIONS))

    def test_countries_come_from_the_pool_and_are_sorted_by_name(self):
        values = [o["value"] for o in places.work_options(["SK", "AT", "DE"])]
        self.assertEqual(values[len(places.REGIONS):], ["AT", "DE", "SK"])

    def test_a_chosen_code_survives_the_pool_losing_it(self):
        # A preference must not vanish because the boards stopped listing it.
        values = [o["value"] for o in places.work_options([], chosen=["PT"])]
        self.assertIn("PT", values)

    def test_options_are_worded_once(self):
        for option in places.work_options(["SK"]):
            self.assertEqual(option["label"], places.label(option["value"]))



class CoveringRegionTests(unittest.TestCase):
    """The other direction: what a *board* can be asked for, for everybody.

    `reachable_codes` decides what one person can take; this decides what one
    request can fetch for all of them. The rule under every case below is that
    None means "ask for everything" — narrowing is only ever allowed to be an
    optimisation, never a filter that loses somebody a job.
    """

    def test_a_country_is_covered_by_its_region(self):
        self.assertEqual(places.covering_region({"SK"}), "EU")
        self.assertEqual(places.covering_region({"SK", "EU"}), "EU")
        self.assertEqual(places.covering_region({"SK", "CZ", "DE", "PT"}), "EU")
        self.assertEqual(places.covering_region({"CA", "US"}), "NA")
        self.assertEqual(places.covering_region({"JP"}), "APAC")

    def test_two_regions_at_once_cannot_be_narrowed(self):
        """A board takes one geography; two of them is two crawls, not one."""
        self.assertIsNone(places.covering_region({"SK", "US"}))
        self.assertIsNone(places.covering_region({"EU", "NA"}))

    def test_nothing_known_is_not_nowhere(self):
        self.assertIsNone(places.covering_region(set()))
        self.assertIsNone(places.covering_region(None))
        self.assertIsNone(places.covering_region({"XX"}))

    def test_somebody_who_can_work_anywhere_stops_the_narrowing(self):
        self.assertIsNone(places.covering_region({"ANY"}))
        self.assertIsNone(places.covering_region({"SK", "ANY"}))

    def test_a_country_in_no_region_narrows_to_nothing(self):
        """ZA, AE and IL are deliberately in no region — so is their crawl."""
        for code in ("ZA", "AE", "IL"):
            self.assertIsNone(places.covering_region({code}), code)
        self.assertIsNone(places.covering_region({"SK", "IL"}))

    def test_every_region_it_can_return_is_a_real_one(self):
        for code in places.LABELS:
            answer = places.covering_region({code})
            self.assertIn(answer, (None, *places.REGION_MEMBERS), code)

    def test_it_agrees_with_reachable_codes(self):
        """Whatever it narrows to has to still contain the people it is for.

        The two functions are the same fact read from opposite ends: if the
        crawl asks a board for `EU`, every code the users can reach had better
        be reachable from `EU` too, or the narrowing dropped somebody.
        """
        for codes in ({"SK"}, {"SK", "CZ"}, {"CA", "US"}, {"AU", "NZ"}):
            region = places.covering_region(codes)
            self.assertIsNotNone(region, codes)
            self.assertTrue(codes <= places.reachable_codes({region}), codes)


class MultiPlaceTests(unittest.TestCase):
    """A posting hiring in five places is five answers, and one column is one.

    Remotive writes "LATAM, Europe, USA, Canada, APAC" into a single location
    field. First-match-wins stored that as `US` and "Americas, Europe, Israel"
    as `IL` — both then *unreachable* for a European, though both say Europe
    out loud, which is exactly the job an EU-remote search exists to find. So
    `codes()` keeps all of them and `primary()` picks the one a card prints.
    """

    def test_every_place_a_posting_names_is_kept(self):
        found = places.codes("remotive", "LATAM, Europe, USA, Canada, APAC")
        self.assertEqual(set(found), {"US", "CA", "EU", "LATAM", "APAC"})

    def test_the_posting_that_says_europe_is_reachable_from_europe(self):
        """The regression itself, stated as the two strings that failed."""
        european = places.reachable_codes({"SK", "EU"})
        for text in ("LATAM, Europe, USA, Canada, APAC", "Americas, Europe, Israel"):
            found = set(places.codes("remotive", text))
            self.assertTrue(european & found, text)
            # ...and the old answer, which was not.
            self.assertEqual(places.country("remotive", text), "EU", text)

    def test_a_us_only_posting_is_still_not_reachable(self):
        """The fix must not hand everybody every job — that was the *other* bug."""
        for text in ("USA only", "Remote, US, Canada", "US, India"):
            found = set(places.codes("remotive", text))
            self.assertFalse(places.reachable_codes({"SK", "EU"}) & found, text)

    def test_the_specific_answer_still_prints_when_it_fits_inside_the_general_one(self):
        """"Berlin, Germany — Europe" is a German job, and the chip says so."""
        self.assertEqual(places.primary(("DE", "EU")), "DE")
        self.assertEqual(places.primary(("CZ",)), "CZ")
        self.assertEqual(places.country("remotive", "Prague, Czechia (Europe)"), "CZ")

    def test_the_widest_answer_prints_when_the_places_span_regions(self):
        """Naming one of five reads as the only one, so the region wins."""
        self.assertEqual(places.primary(("IL", "EU")), "EU")
        self.assertEqual(places.primary(("US", "CA", "EU", "LATAM", "APAC")), "EU")

    def test_the_boards_own_spellings_of_a_region_are_matched(self):
        """"northern america" is what Remotive writes, and it matched nothing."""
        self.assertIn("NA", places.codes("remotive", "Northern America, Europe"))

    def test_a_set_with_no_region_in_it_falls_back_to_the_most_specific(self):
        self.assertEqual(places.primary(("US", "IN")), "US")
        self.assertIsNone(places.primary(()))
        self.assertIsNone(places.primary(("XX",)))

    def test_anywhere_is_still_only_reached_when_nothing_narrower_matched(self):
        # The specific → general rule survives: a posting saying "Anywhere in
        # Europe" is a European posting, not a worldwide one.
        self.assertEqual(places.codes("remoteok", "Anywhere in Europe"), ("EU",))
        self.assertEqual(places.codes("remoteok", "Worldwide"), ("ANY",))

    def test_the_board_is_still_only_a_fallback(self):
        self.assertEqual(places.codes("profesia", "Vranov nad Topľou"), ("SK",))
        self.assertEqual(places.codes("profesia", "Praha"), ("CZ",))
        self.assertEqual(places.codes("remoteok", "Contact us for details"), ())

    def test_codes_and_country_are_one_derivation(self):
        """`jobs.country` is the printed half of `jobs.countries`, never a second
        opinion — the two columns disagreeing is the bug this replaced."""
        for text in ("Bratislava", "EMEA", "Anywhere", "LATAM, Europe, USA",
                     "Berlin, Germany", "", "Contact us"):
            found = places.codes("remotive", text)
            self.assertEqual(places.country("remotive", text), places.primary(found))
            self.assertEqual(places.unpack(places.pack(found)), set(found), text)


class PackingTests(unittest.TestCase):
    """The stored shape: `|EU|US|`, delimited on both ends so `|US|` cannot
    match inside another code."""

    def test_a_packed_set_round_trips(self):
        self.assertEqual(places.pack(("EU", "US")), "|EU|US|")
        self.assertEqual(places.unpack("|EU|US|"), {"EU", "US"})

    def test_nothing_packs_to_null_rather_than_to_an_empty_string(self):
        # NULL is what the column holds for a row nothing placed, and what
        # `COUNTRIES_SQL` falls back on.
        self.assertIsNone(places.pack(()))
        self.assertIsNone(places.pack(("XX",)))
        self.assertEqual(places.unpack(None), set())
        self.assertEqual(places.unpack(""), set())

    def test_a_token_cannot_match_inside_another_code(self):
        packed = places.pack(("LATAM", "US"))
        self.assertIn(places.token("US").strip("%"), packed)
        # "NA" is a real code and a substring of "LATAM" — the delimiters are
        # what stop the filter handing a Latin-American job to a Canadian.
        self.assertNotIn(places.token("NA").strip("%"), packed)

    def test_a_row_from_before_the_column_still_places_itself(self):
        """`countries` is NULL between the column being added and the backfill;
        scoring has to be right in that window, not after it."""
        self.assertEqual(places.stored_codes(None, "SK"), {"SK"})
        self.assertEqual(places.stored_codes("|EU|US|", "EU"), {"EU", "US"})
        self.assertEqual(places.stored_codes(None, None), set())


if __name__ == "__main__":
    unittest.main()

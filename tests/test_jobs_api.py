"""Tests for Phase 6's server side: the job detail endpoint and list paging.

Everything else in Phase 6 is `templates/`, CSS and `static/js/app.js`, which
this suite has no way to reach. What it can hold on to is the pair of contracts
the new UI leans on: `/api/jobs/<id>` is scoped to the caller and carries the
description no list ships, and `/api/jobs` pages instead of silently truncating.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import unittest

# `app` is imported *through* test_auth, never before it: that module turns the
# rate limiter off before importing the app, and the app reads config once, at
# import time. Importing `app` here directly would leave login rate-limited and
# every client_for() in this file would get a 429 instead of a session.
from jobmatch import places, salary
from tests.test_auth import PASSWORD, AuthTestCase, webapp


class JobDetailTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.job_id = self.add_job("Python developer")
        self.make_user("a@example.com")
        self.client = self.client_for("a@example.com")

    def test_detail_carries_the_description_and_the_callers_own_status(self):
        job = self.client.get(f"/api/jobs/{self.job_id}").get_json()["job"]
        self.assertEqual(job["id"], self.job_id)
        self.assertIn("Python and React", job["description"])
        self.assertEqual(job["status"], "new")
        self.assertEqual(job["status_label"], "New")
        # The list is deliberately without it: 4 KB per row, 50 rows a page.
        listed = self.client.get("/api/jobs").get_json()["jobs"][0]
        self.assertNotIn("description", listed)

    def test_detail_and_list_word_a_job_the_same_way(self):
        """Both go through `_job_payload`, so a job cannot read two ways."""
        detail = self.client.get(f"/api/jobs/{self.job_id}").get_json()["job"]
        listed = self.client.get("/api/jobs").get_json()["jobs"][0]
        for key in ("title", "source_label", "worktype_label", "match_score",
                    "score_breakdown", "posted_display", "salary_hourly"):
            self.assertEqual(detail[key], listed[key], key)

    def test_an_unknown_job_is_a_404_not_a_crash(self):
        res = self.client.get("/api/jobs/999999")
        self.assertEqual(res.status_code, 404)
        self.assertIn("error", res.get_json())

    def test_a_job_scanned_in_after_signup_is_materialized_rather_than_missed(self):
        """A job with no `user_jobs` row yet is still this user's to read."""
        fresh_id = self.add_job("Later arrival")
        self.conn.execute(
            "DELETE FROM user_jobs WHERE job_id = :job_id", {"job_id": fresh_id}
        )
        self.conn.commit()
        job = self.client.get(f"/api/jobs/{fresh_id}").get_json()["job"]
        self.assertEqual(job["status"], "new")

    def test_the_page_route_is_behind_auth_like_every_other_page(self):
        self.assertEqual(self.client.get(f"/jobs/{self.job_id}").status_code, 200)
        signed_out = webapp.app.test_client().get(f"/jobs/{self.job_id}")
        self.assertEqual(signed_out.status_code, 302)


class JobDetailIsolationTests(AuthTestCase):
    def test_the_detail_endpoint_is_scoped_to_the_caller(self):
        """B's status for a shared job is never what A is shown."""
        job_id = self.add_job("Python developer")
        self.make_user("a@example.com")
        self.make_user("b@example.com", PASSWORD)
        client_a = self.client_for("a@example.com")
        client_b = self.client_for("b@example.com")

        client_a.post(f"/api/jobs/{job_id}/status", json={"status": "declined"})
        self.assertEqual(client_a.get(f"/api/jobs/{job_id}").get_json()["job"]["status"],
                         "declined")
        self.assertEqual(client_b.get(f"/api/jobs/{job_id}").get_json()["job"]["status"],
                         "new")


class JobPagingTests(AuthTestCase):
    """`JOB_LIMIT` used to be a truncation the client apologised for in prose."""

    def setUp(self):
        super().setUp()
        for n in range(12):
            self.add_job(f"Job {n:02d}")
        self.make_user("a@example.com")
        self.client = self.client_for("a@example.com")

    def get(self, query=""):
        return self.client.get(f"/api/jobs?{query}").get_json()

    def test_total_counts_the_whole_filter_not_the_page(self):
        page = self.get("limit=5")
        self.assertEqual(page["count"], 5)
        self.assertEqual(page["total"], 12)
        self.assertTrue(page["has_more"])

    def test_offset_walks_the_list_without_repeating_or_skipping_a_row(self):
        seen = []
        for offset in (0, 5, 10):
            page = self.get(f"limit=5&offset={offset}")
            seen.extend(job["id"] for job in page["jobs"])
        self.assertEqual(len(seen), 12)
        self.assertEqual(len(set(seen)), 12, "a page boundary repeated or lost a row")

    def test_the_last_page_says_there_is_no_more(self):
        page = self.get("limit=5&offset=10")
        self.assertEqual(page["count"], 2)
        self.assertFalse(page["has_more"])

    def test_a_limit_past_the_ceiling_is_clamped(self):
        """One caller must not be able to ask for the whole table."""
        page = self.get("limit=999999")
        self.assertLessEqual(page["count"], webapp.JOB_LIMIT)

    def test_junk_paging_parameters_fall_back_to_the_first_page(self):
        page = self.get("limit=abc&offset=-4")
        self.assertEqual(page["offset"], 0)
        self.assertEqual(page["count"], 12)

    def test_paging_respects_the_filters_it_is_paging_through(self):
        job_id = self.get("limit=1")["jobs"][0]["id"]
        self.client.post(f"/api/jobs/{job_id}/status", json={"status": "declined"})
        page = self.get("status=new")
        self.assertEqual(page["total"], 11)
        self.assertNotIn(job_id, [job["id"] for job in page["jobs"]])


class JobFacetTests(AuthTestCase):
    """Pay, work mode and country: what the Jobs page shows and filters on.

    These three are the visible half of the same change — a chip on a card is
    only useful if the filter under it selects on the same fact — so the
    payload and the WHERE clause are asserted against one another here.
    """

    def setUp(self):
        super().setUp()
        # A Slovak on-site job at 1500–2000 €/month → ≈9.4–12.5 an hour…
        self.sk = self.add_job(
            "Bratislava backend", source="profesia", location="bratislava",
            worktype="onsite", country="SK", salary="1500 - 2000 eur/mesiac",
            salary_min=1500, salary_max=2000, salary_currency="EUR",
            salary_period="month",
        )
        # …an American remote one at 70–90k a year → ≈36–47, which is the pair
        # of numbers that makes an hourly floor mean anything across boards.
        self.us = self.add_job(
            "Remote platform engineer", source="remoteok", location="usa only",
            worktype="remote", country="US", salary="$70k - $90k",
            salary_min=70000, salary_max=90000, salary_currency="USD",
            salary_period="year",
        )
        # …and one that quotes nothing and could not be placed.
        self.quiet = self.add_job(
            "Hybrid nobody placed", source="remotive", location="ask us",
            worktype="hybrid",
        )
        self.make_user("a@example.com")
        self.client = self.client_for("a@example.com")

    def ids(self, query=""):
        page = self.client.get(f"/api/jobs?status=new&{query}").get_json()
        # `total` is the count behind the paging, not the length of this page —
        # a filter that only trimmed the visible page would still be wrong.
        self.assertEqual(page["total"], len(page["jobs"]))
        return {job["id"] for job in page["jobs"]}

    def test_a_card_carries_the_pay_and_the_country_in_words(self):
        job = next(j for j in self.client.get("/api/jobs").get_json()["jobs"]
                   if j["id"] == self.sk)
        self.assertEqual(job["country"], "SK")
        self.assertEqual(job["country_label"], "Slovakia")
        self.assertIn("2 000", job["salary_display"].replace("\u202f", " "))
        self.assertIn("/mo", job["salary_display"])
        self.assertTrue(job["salary_hourly"].startswith("≈"))

    def test_a_job_with_no_salary_says_so_rather_than_showing_an_empty_string(self):
        job = next(j for j in self.client.get("/api/jobs").get_json()["jobs"]
                   if j["id"] == self.quiet)
        self.assertIsNone(job["salary_display"])
        self.assertEqual(job["country_label"], "")

    def test_work_mode_filters_on_the_stored_worktype(self):
        self.assertEqual(self.ids("worktype=remote"), {self.us})
        self.assertEqual(self.ids("worktype=onsite"), {self.sk})

    def test_country_filters_on_the_stored_code(self):
        self.assertEqual(self.ids("country=SK"), {self.sk})
        self.assertEqual(self.ids("country=US"), {self.us})

    def test_pay_listed_hides_the_postings_that_quote_nothing(self):
        self.assertEqual(self.ids("pay=listed"), {self.sk, self.us})

    def test_a_pay_floor_compares_hourly_whatever_period_the_board_quoted(self):
        """1 500 €/month and $70k/year are only comparable per hour."""
        self.assertEqual(self.ids("pay=10"), {self.sk, self.us})
        self.assertEqual(self.ids("pay=30"), {self.us})

    def test_a_filter_value_the_server_does_not_know_is_ignored_not_obeyed(self):
        """A hand-edited query string must not silently empty the list."""
        everything = {self.sk, self.us, self.quiet}
        self.assertEqual(self.ids("country=XX"), everything)
        self.assertEqual(self.ids("worktype=teleport"), everything)
        self.assertEqual(self.ids("pay=7"), everything)

    def test_best_pay_sorts_by_the_hourly_rate_and_puts_the_silent_ones_last(self):
        order = [job["id"] for job in
                 self.client.get("/api/jobs?status=new&sort=pay").get_json()["jobs"]]
        self.assertEqual(order, [self.us, self.sk, self.quiet])

    def test_an_unknown_sort_falls_back_rather_than_erroring(self):
        res = self.client.get("/api/jobs?status=new&sort=nonsense")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["total"], 3)

    def test_the_country_dropdown_offers_only_what_the_pool_holds(self):
        settings = self.client.get("/api/settings").get_json()
        self.assertEqual([c["value"] for c in settings["available_countries"]],
                         ["SK", "US"])
        # The floors are euros an hour now, so the currency is part of the
        # label and the label is the server's — a page must not word it.
        self.assertEqual([f["value"] for f in settings["pay_floors"]],
                         list(webapp.PAY_FLOORS))
        self.assertEqual(settings["pay_floors"][0]["label"], "€10+ an hour")


class CrossCurrencyPayTests(AuthTestCase):
    """Pay across two currencies — the half "per hour" never fixed.

    Putting every posting on one *period* made a monthly Slovak wage and an
    annual American salary comparable, and stopped there: the number was still
    in whatever money the board quoted, so 140 000 Kč a month and 140 000 € a
    month were one number to the filter and to the sort. jobs.cz is what put a
    currency two orders of magnitude off the euro into the pool and made that
    reachable rather than theoretical.
    """

    def setUp(self):
        super().setUp()
        # An ordinary Czech monthly wage: 40 000 Kč ≈ €1 656 ≈ €10.35 an hour.
        # Read as euros it was €250 an hour and topped every list in the app.
        self.cz = self.add_job(
            "Praha backend", source="jobscz", country="CZ",
            salary="40 000 Kč", salary_min=40000, salary_max=40000,
            salary_currency="CZK", salary_period="month",
        )
        # A better-paid Slovak job at a much smaller number: €2 400 ≈ €15/h.
        self.sk = self.add_job(
            "Bratislava backend", source="profesia", country="SK",
            salary="2 400 eur/mesiac", salary_min=2400, salary_max=2400,
            salary_currency="EUR", salary_period="month",
        )
        # And a board that quoted a currency we hold no rate for.
        self.unknown = self.add_job(
            "Stockholm backend", source="arbeitnow", country="SE",
            salary="60 000 SEK", salary_min=60000, salary_max=60000,
            salary_currency="SEK", salary_period="month",
        )
        self.make_user("a@example.com")
        self.client = self.client_for("a@example.com")

    def ids(self, query=""):
        page = self.client.get(f"/api/jobs?status=new&{query}").get_json()
        return {job["id"] for job in page["jobs"]}

    def order(self):
        return [job["id"] for job in
                self.client.get("/api/jobs?status=new&sort=pay").get_json()["jobs"]]

    def test_the_bigger_number_is_not_the_better_paid_job(self):
        """40 000 of one currency against 2 400 of another."""
        self.assertEqual(self.order()[:2], [self.sk, self.cz])

    def test_a_pay_floor_is_read_in_the_currency_it_is_labelled_in(self):
        # €20/h clears neither; €10/h clears both, and the Czech job used to
        # clear €50 on the strength of its digits alone.
        self.assertEqual(self.ids("pay=20"), set())
        self.assertEqual(self.ids("pay=10"), {self.sk, self.cz})
        self.assertNotIn(self.cz, self.ids("pay=50"))

    def test_a_currency_with_no_rate_ranks_last_rather_than_at_par(self):
        """Same shape as a job that quotes nothing: unknown, never zero."""
        self.assertEqual(self.order()[-1], self.unknown)
        self.assertNotIn(self.unknown, self.ids("pay=10"))
        # It still quotes *something*, and that filter asks a different
        # question — whether the board named a figure at all.
        self.assertIn(self.unknown, self.ids("pay=listed"))

    def test_the_card_keeps_the_boards_money_and_adds_the_comparison(self):
        job = next(j for j in self.client.get("/api/jobs").get_json()["jobs"]
                   if j["id"] == self.cz)
        self.assertIn("Kč", job["salary_display"])
        self.assertIn("€", job["salary_hourly"])
        self.assertIn("24.15", job["salary_hourly_title"])

    def test_a_euro_job_carries_no_conversion_note_to_explain(self):
        job = next(j for j in self.client.get("/api/jobs").get_json()["jobs"]
                   if j["id"] == self.sk)
        self.assertEqual(job["salary_hourly_title"], "")

    def test_the_sql_and_the_python_are_one_derivation(self):
        """`HOURLY_EUR_SQL` is generated from the tables `hourly_eur` reads.

        Generated, but not therefore proven: the SQL divides by two CASEs and
        the Python by two dict lookups, and only running both over every
        currency and period the pool can hold says they agree. A drift here is
        a card printing one number while the filter selects on another.
        """
        for currency in list(salary.EUR_RATES) + ["SEK", None]:
            for period in list(salary.HOURS_PER) + [None]:
                self.add_job(
                    f"pair {currency} {period}", source="remotive",
                    salary_min=9000, salary_max=12000,
                    salary_currency=currency, salary_period=period,
                )
        rows = self.conn.execute(
            f"SELECT j.salary_min, j.salary_max, j.salary_currency,"
            f" j.salary_period, {salary.HOURLY_EUR_SQL} AS sql_rate"
            f" FROM jobs j WHERE j.salary_min IS NOT NULL"
        ).fetchall()
        self.assertGreaterEqual(len(rows), len(salary.EUR_RATES) * len(salary.HOURS_PER))
        compared = 0
        for row in rows:
            _, expected = salary.hourly_eur(
                row["salary_min"], row["salary_max"],
                row["salary_period"], row["salary_currency"])
            if expected is None:
                self.assertIsNone(row["sql_rate"], dict(row))
            else:
                self.assertAlmostEqual(row["sql_rate"], expected, delta=0.06, msg=dict(row))
                compared += 1
        self.assertGreater(compared, 0, "nothing was actually compared")


class ReachableFilterTests(AuthTestCase):
    """"Somewhere I can work" — the filter and the score off one derivation.

    The scoring half is pinned in `test_scoring`; what is asserted here is that
    the Jobs page selects on exactly the same expansion, because a list that
    disagreed with the score under it would be the worse of the two bugs.
    """

    def setUp(self):
        super().setUp()
        self.sk = self.add_job("Bratislava backend", location="bratislava",
                               worktype="onsite", country="SK")
        self.de = self.add_job("Berlin remote", location="berlin",
                               worktype="remote", country="DE")
        self.us = self.add_job("US remote", location="usa only",
                               worktype="remote", country="US")
        self.anywhere = self.add_job("Worldwide remote", location="anywhere",
                                     worktype="remote", country="ANY")
        self.unplaced = self.add_job("Nobody placed this", location="ask us",
                                     worktype="remote")
        self.make_user("a@example.com")
        self.client = self.client_for("a@example.com")

    def ids(self, query=""):
        page = self.client.get(f"/api/jobs?status=new&{query}").get_json()
        return {job["id"] for job in page["jobs"]}

    def settings(self, **updates):
        self.client.put("/api/settings", json=updates)
        return self.client.get("/api/settings").get_json()

    def test_it_keeps_the_reachable_ones_and_the_worldwide_posting(self):
        self.settings(user_regions=["SK", "EU"])
        self.assertEqual(self.ids("country=reachable"),
                         {self.sk, self.de, self.anywhere})

    def test_a_country_still_filters_to_itself(self):
        self.settings(user_regions=["SK", "EU"])
        self.assertEqual(self.ids("country=DE"), {self.de})

    def test_with_nothing_answered_it_is_ignored_rather_than_obeyed(self):
        """The rule every unrecognised filter value here follows: never empty
        the page. Nothing to expand means nothing to filter on."""
        everything = {self.sk, self.de, self.us, self.anywhere, self.unplaced}
        self.assertEqual(self.ids("country=reachable"), everything)

    def test_the_option_appears_only_once_there_is_an_answer_to_expand(self):
        def offered(s):
            return [c["value"] for c in s["available_countries"]]

        self.assertNotIn("reachable", offered(self.settings()))
        after = self.settings(user_regions=["SK"])
        self.assertEqual(offered(after)[0], "reachable")
        self.assertEqual(after["available_countries"][0]["label"],
                         "Somewhere I can work")

    def test_the_town_is_enough_to_answer_it(self):
        """A user who never opened the picker still gets their own country and
        its region, derived from the location they already gave."""
        after = self.settings(user_location="bratislava")
        self.assertEqual(after["user_regions"], [])
        self.assertEqual(after["effective_regions"], ["EU", "SK"])
        self.assertEqual(self.ids("country=reachable"),
                         {self.sk, self.de, self.anywhere})

    def test_every_code_in_the_answer_has_a_chip_to_sit_on(self):
        """The picker shows the effective answer as its active chips, so a code
        with no chip would be dropped the next time the profile was saved —
        which is what a pool with no Slovak jobs in it used to do to a user in
        Bratislava."""
        self.conn.execute("UPDATE jobs SET country = NULL")
        self.conn.commit()
        after = self.settings(user_location="bratislava")
        offered = {o["value"] for o in after["work_options"]}
        self.assertEqual(set(after["effective_regions"]) - offered, set())

    def test_a_picked_answer_overrides_the_derived_one(self):
        after = self.settings(user_location="bratislava", user_regions=["US"])
        self.assertEqual(after["effective_regions"], ["US"])
        self.assertEqual(self.ids("country=reachable"), {self.us, self.anywhere})

    def test_codes_the_server_does_not_know_are_dropped_on_the_way_in(self):
        after = self.settings(user_regions=["sk", "XX", " eu "])
        self.assertEqual(after["user_regions"], ["EU", "SK"])

    def test_changing_it_rescores_without_a_rescan(self):
        """It moves what "matched" means, so it belongs in RESCORE_KEYS."""
        def score(job_id):
            return self.client.get(f"/api/jobs/{job_id}").get_json()["job"]["match_score"]

        self.settings(user_regions=["US"], user_skills=[], weight_skill=0,
                      weight_worktype=0, weight_location=1, weight_seniority=0)
        self.assertEqual(score(self.us), 100.0)
        self.assertEqual(score(self.de), 0.0)
        res = self.client.put("/api/settings", json={"user_regions": ["EU"]})
        self.assertTrue(res.get_json()["rescored"])
        self.assertEqual(score(self.de), 100.0)
        self.assertEqual(score(self.us), 0.0)


class TrackerGroupTests(AuthTestCase):
    """The tracker's tabs are server-defined, and must cover every status.

    A status in no group is an application that vanishes from the tracker the
    moment somebody selects it — the table only ever shows one group.
    """

    def setUp(self):
        super().setUp()
        self.make_user("a@example.com")
        self.client = self.client_for("a@example.com")
        self.groups = self.client.get("/api/settings").get_json()["application_groups"]

    def test_every_status_belongs_to_exactly_one_group(self):
        seen = [status for group in self.groups for status in group["statuses"]]
        self.assertEqual(sorted(seen), sorted(webapp.APPLICATION_STATUSES))
        self.assertEqual(len(seen), len(set(seen)), "a status is in two tabs")

    def test_everything_is_the_first_tab_and_filters_nothing(self):
        self.assertEqual(self.groups[0]["value"], "all")
        self.assertEqual(self.groups[0]["statuses"], [])

    def test_waiting_is_the_two_statuses_that_are_the_same_wait(self):
        waiting = next(g for g in self.groups if g["value"] == "waiting")
        self.assertEqual(sorted(waiting["statuses"]), ["applied", "no_response"])

    def test_the_groups_and_the_dropdown_speak_of_the_same_statuses(self):
        """The tabs filter what the <select> in each row can set."""
        dropdown = {s["value"] for s in
                    self.client.get("/api/settings").get_json()["application_statuses"]}
        self.assertEqual({s for g in self.groups for s in g["statuses"]}, dropdown)


if __name__ == "__main__":
    unittest.main()


class MultiPlaceJobTests(AuthTestCase):
    """A posting hiring in five places, from the card to the WHERE clause.

    Remotive writes "LATAM, Europe, USA, Canada, APAC" into one location field.
    Storing the first match made it `US` — unreachable for a European, though
    it says Europe out loud — so the set is stored too, and every question
    about reach is asked of the set while the card still prints one thing.
    """

    def setUp(self):
        super().setUp()
        found = places.codes("remotive", "LATAM, Europe, USA, Canada, APAC")
        self.many = self.add_job(
            "Everywhere platform engineer", source="remotive",
            location="LATAM, Europe, USA, Canada, APAC", worktype="remote",
            country=places.primary(found), countries=places.pack(found),
        )
        self.us = self.add_job(
            "US only", source="remotive", location="USA only", worktype="remote",
            country="US", countries=places.pack(("US",)),
        )
        self.make_user("a@example.com")
        self.client = self.client_for("a@example.com")
        self.client.put("/api/settings", json={"user_regions": ["SK", "EU"]})

    def ids(self, query=""):
        return {job["id"] for job in
                self.client.get(f"/api/jobs?status=new&{query}").get_json()["jobs"]}

    def job(self, job_id):
        return next(j for j in self.client.get("/api/jobs").get_json()["jobs"]
                    if j["id"] == job_id)

    def test_a_european_is_offered_the_posting_that_says_europe(self):
        """The regression: this used to be stored `US` and filtered out."""
        self.assertEqual(self.ids("country=reachable"), {self.many})

    def test_a_country_the_posting_names_finds_it_too(self):
        """It hires in the US as well — picking "United States" must not hide it
        just because the card prints Europe."""
        self.assertEqual(self.ids("country=US"), {self.many, self.us})
        self.assertEqual(self.ids("country=EU"), {self.many})

    def test_the_card_prints_one_place_and_says_how_many_it_stands_for(self):
        self.assertEqual(self.job(self.many)["country"], "EU")
        self.assertEqual(self.job(self.many)["country_label"], "Europe +4")
        self.assertEqual(self.job(self.us)["country_label"], "United States")

    def test_the_other_four_are_named_in_words_rather_than_left_as_a_number(self):
        """"+4" with nothing behind it is a worse chip than the wrong one was."""
        self.assertEqual(
            self.job(self.many)["country_title"],
            "Europe, Asia-Pacific, Canada, Latin America, United States")
        self.assertEqual(self.job(self.us)["country_title"], "")

    def test_the_score_and_the_list_agree_about_it(self):
        """The two read one derivation, so a job on the list is a job the score
        says is reachable — the failure that would matter most."""
        listed = self.job(self.many)
        self.assertEqual(listed["score_breakdown"]["location"], 1.0)
        self.assertEqual(self.job(self.us)["score_breakdown"]["location"], 0.0)

    def test_the_dropdown_offers_every_place_the_pool_can_be_filtered_to(self):
        """Five codes are in there, and only one of them is printed anywhere."""
        offered = [c["value"] for c in
                   self.client.get("/api/settings").get_json()["available_countries"]]
        self.assertEqual(set(offered) - {"reachable"},
                         {"EU", "LATAM", "APAC", "US", "CA"})


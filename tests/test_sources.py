"""Tests for the adapters themselves — Phase 8's "harden profesia" bullet.

The failure these are written against is the quiet one. A scraper that stops
understanding a page does not raise: it parses zero rows, returns zero stubs and
finishes green, which is character-for-character what an incremental scan of a
board with nothing new looks like. So the contract every adapter now keeps is
`ctx.seen(n)` — *listings the board showed me*, before any filtering — and these
tests pin the two cases apart: everything already known (seen, no stubs) versus
a page the adapter can no longer read (nothing seen at all).

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import json
import unittest
from unittest import mock

from jobmatch import places, salary
from jobmatch.sources import (
    arbeitnow,
    jobicy,
    jobscz,
    kariera,
    profesia,
    remoteok,
    remotive,
)
from jobmatch.sources.base import ScanContext


def offer_html(offer_id, title, extra=""):
    return f"""
      <li class="list-row">
        <h2><a id="offer{offer_id}" href="/praca/acme/O{offer_id}">
          <span class="title">{title}</span></a></h2>
        <span class="employer">ACME s.r.o.</span>
        <span class="job-location" title="Bratislava I">Bratislava</span>
        <span class="label-green">1 500 - 2 000 EUR/mesiac</span>
        <span class="info">pred 2 dňami</span>
        {extra}
      </li>
    """


def results_page(*offers):
    return "<html><body><ul class='list'>" + "".join(offers) + "</ul></body></html>"


class RecordingContext(ScanContext):
    """A ScanContext that remembers what an adapter reported through it."""

    def __init__(self, stop_after=None, regions=()):
        self.seen_counts = []
        self.warnings = []
        self.phases = []
        self._calls = 0
        self._stop_after = stop_after
        super().__init__(
            progress=self.phases.append,
            stopped=self._should_stop,
            seen=self.seen_counts.append,
            warn=self.warnings.append,
            regions=regions,
        )

    def _should_stop(self):
        self._calls += 1
        return self._stop_after is not None and self._calls > self._stop_after

    def sleep(self, lo, hi):
        return not self.stopped()   # tests do not wait 13 seconds per page

    @property
    def total_seen(self):
        return sum(self.seen_counts)


# ── Parsing one result page ──────────────────────────────────

class ProfesiaParseTests(unittest.TestCase):
    def test_a_normal_page_yields_stubs(self):
        html = results_page(
            offer_html("111", "Python developer"),
            offer_html("222", "Junior Python programátor"),
        )
        stubs, matched, listed = profesia.parse_jobs(html, "python", set())

        self.assertEqual([s["source_id"] for s in stubs], ["111", "222"])
        self.assertEqual((matched, listed), (2, 2))
        self.assertEqual(stubs[0]["company"], "acme s.r.o.")
        self.assertEqual(stubs[0]["location"], "bratislava (bratislava i)")
        self.assertEqual(stubs[0]["link"], "https://www.profesia.sk/praca/acme/O111")

    def test_offers_we_already_have_still_count_as_listings(self):
        """The load-bearing distinction: known ≠ invisible.

        Every offer on the page is one we stored last night, so there are no
        stubs — and `listed` is what says the page was read perfectly well.
        """
        html = results_page(
            offer_html("111", "Python developer"),
            offer_html("222", "Python developer II"),
        )
        stubs, matched, listed = profesia.parse_jobs(html, "python", {"111", "222"})

        self.assertEqual(stubs, [])
        self.assertEqual(matched, 2, "both matched the term")
        self.assertEqual(listed, 2, "and both were on the page")

    def test_offers_that_do_not_match_the_term_still_count_as_listings(self):
        html = results_page(offer_html("111", "Účtovník"))
        stubs, matched, listed = profesia.parse_jobs(html, "python", set())
        self.assertEqual((stubs, matched, listed), ([], 0, 1))

    def test_promo_tiles_are_not_listings(self):
        html = (
            "<html><body><ul class='list'>"
            "<li class='list-row promo-tile'><h2><a id='offer9' "
            "href='/praca/x/O9'><span class='title'>Python</span></a></h2></li>"
            + offer_html("111", "Python developer")
            + "</ul></body></html>"
        )
        _, _, listed = profesia.parse_jobs(html, "python", set())
        self.assertEqual(listed, 1)

    def test_a_page_without_the_list_container_lists_nothing(self):
        """What a redesign looks like, and what raises the alarm."""
        html = "<html><body><div class='results'>…</div></body></html>"
        self.assertEqual(profesia.parse_jobs(html, "python", set()), ([], 0, 0))

    def test_rows_whose_title_link_moved_are_not_counted_as_read(self):
        """A subtler redesign: the rows survive, the link inside them does not.

        Counting the <li>s would call this a healthy page of 2 listings that
        happened to yield nothing, which is exactly the lie being fixed.
        """
        html = results_page(
            "<li class='list-row'><h2><span>Python developer</span></h2></li>",
            "<li class='list-row'><h2><a id='offer5' href='/inzerat/5'>"
            "<span class='title'>Python developer</span></a></h2></li>",
        )
        self.assertEqual(profesia.parse_jobs(html, "python", set()), ([], 0, 0))


# ── Walking the pages ────────────────────────────────────────

class FakePage:
    """The two Playwright calls the profesia search makes, over canned pages."""

    def __init__(self, pages, url="https://www.profesia.sk/praca/?search_anywhere=python"):
        self.pages = pages          # url substring → html, or a callable
        self.url = url
        self.visited = []

    def goto(self, url, **kwargs):
        self.visited.append(url)
        page_num = 1
        if "page_num=" in url:
            page_num = int(url.split("page_num=")[1].split("&")[0])
        self._html = self.pages(page_num) if callable(self.pages) else self.pages[page_num - 1]

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return self._html


class ProfesiaSearchTests(unittest.TestCase):
    def setUp(self):
        self.source = profesia.ProfesiaSource()

    def test_the_first_page_is_fetched_once(self):
        """It used to be fetched twice — once to learn the redirect target and
        again as page 1 — with no politeness delay in between."""
        page = FakePage([results_page(offer_html("111", "Python developer")),
                         results_page()])
        ctx = RecordingContext()
        stubs = self.source._search_term(page, "python", 7, set(), ctx)

        self.assertEqual(len(stubs), 1)
        self.assertIn("search_anywhere=python", page.visited[0])
        self.assertEqual(
            page.visited.count(page.visited[0]), 1,
            "the first page is requested once, not once to find the URL and again to read it",
        )
        self.assertEqual([u for u in page.visited if "page_num=" not in u], page.visited[:1])

    def test_pagination_follows_the_redirected_url(self):
        page = FakePage([
            results_page(*[offer_html(str(i), "Python developer") for i in range(3)]),
            results_page(offer_html("50", "Python developer")),
            results_page(),
        ])
        ctx = RecordingContext()
        stubs = self.source._search_term(page, "python", 7, set(), ctx)

        self.assertEqual(len(stubs), 4)
        self.assertEqual(len(page.visited), 3)
        self.assertTrue(page.visited[1].endswith("&page_num=2"))
        self.assertEqual(ctx.seen_counts, [3, 1, 0])

    def test_an_empty_first_page_stops_immediately(self):
        page = FakePage([results_page(), results_page()])
        ctx = RecordingContext()

        self.assertEqual(self.source._search_term(page, "python", 7, set(), ctx), [])
        self.assertEqual(len(page.visited), 1, "no point asking for page 2 of nothing")
        self.assertEqual(ctx.total_seen, 0, "and the scan is told nothing was seen")

    def test_a_board_that_never_runs_out_is_capped(self):
        """Without the cap this is an infinite loop against a live site."""
        page = FakePage(lambda pg: results_page(
            offer_html(f"{pg}1", "Python developer"),
            offer_html(f"{pg}2", "Python developer"),
        ))
        ctx = RecordingContext()
        stubs = self.source._search_term(page, "python", 7, set(), ctx)

        self.assertEqual(len(page.visited), profesia.MAX_PAGES)
        self.assertEqual(len(stubs), profesia.MAX_PAGES * 2)

    def test_a_page_that_never_loads_is_retried_then_reported(self):
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        page = FakePage([results_page()])
        page.goto = mock.Mock(side_effect=PlaywrightTimeoutError("timeout"))
        ctx = RecordingContext()

        stubs = self.source._search_term(page, "python", 7, set(), ctx)

        self.assertEqual(stubs, [])
        self.assertEqual(page.goto.call_count, 2, "retried once before giving up")
        self.assertEqual(len(ctx.warnings), 1, "and said so rather than shrugging")
        self.assertIn("page 1", ctx.warnings[0])

    def test_a_cancelled_scan_stops_between_pages(self):
        page = FakePage(lambda pg: results_page(
            offer_html(f"{pg}1", "Python developer"),
        ))
        ctx = RecordingContext(stop_after=3)
        self.source._search_term(page, "python", 7, set(), ctx)
        self.assertLess(len(page.visited), profesia.MAX_PAGES)


# ── The same contract, on the other Slovak board ─────────────

def kariera_offer(offer_id, title="Python developer", href=None, classes="offer"):
    href = f"/pracovna-ponuka/{offer_id}/python-developer" if href is None else href
    return (f'<div class="{classes}"><h2 class="offer-title">'
            f'<a href="{href}">{title}</a></h2>'
            f'<span class="offer-employer">ACME</span></div>')


def kariera_page(*offers):
    return "<html><body>" + "".join(offers) + "</body></html>"


class KarieraSeenTests(unittest.TestCase):
    """Kariéra answers the same two questions Profesia and Jobs.cz do, and for
    three of Phase 9's sessions it answered the second one by counting the card
    container — which is a count that cannot go wrong, and so an alarm that
    cannot fire. Driven against the live board on 2026-09-22, four realistic
    redesigns (the title heading renamed, its `h2` changed, the offer URL
    reshaped, the id dropped from it) each left six cards standing while the
    parser read nothing at all.
    """

    def search(self, html, known_ids=(), term="python"):
        ctx = RecordingContext()
        with mock.patch.object(kariera, "http_get", return_value=html):
            stubs = kariera.KarieraSource()._search_term(term, 7, set(known_ids), ctx)
        return stubs, ctx

    def test_a_page_of_offers_we_already_know_is_still_reported_as_seen(self):
        html = kariera_page(*(kariera_offer(i) for i in range(3)))

        stubs, ctx = self.search(html, known_ids={"0", "1", "2"})

        self.assertEqual(stubs, [], "nothing new")
        self.assertEqual(ctx.total_seen, 3, "but the board answered with three")

    def test_a_page_this_parser_cannot_read_lists_nothing(self):
        stubs, ctx = self.search("<html><body><div>redesign</div></body></html>")

        self.assertEqual(stubs, [])
        self.assertEqual(ctx.total_seen, 0)

    def test_an_offer_whose_title_link_moved_is_not_counted_as_read(self):
        """The half-redesign: the cards are all still there, and unreadable."""
        html = kariera_page(kariera_offer(1).replace("offer-title", "title"),
                            kariera_offer(2))

        stubs, ctx = self.search(html)

        self.assertEqual(ctx.total_seen, 1, "a half-redesign must still trip the alarm")
        self.assertEqual([s["source_id"] for s in stubs], ["2"])

    def test_an_offer_url_this_parser_cannot_read_is_not_counted_as_read(self):
        html = kariera_page(kariera_offer(1, href="/ponuka/1/python-developer"),
                            kariera_offer(2))

        stubs, ctx = self.search(html)

        self.assertEqual(ctx.total_seen, 1)
        self.assertEqual([s["source_id"] for s in stubs], ["2"])

    def test_promoted_slots_are_neither_read_nor_allowed_to_end_the_crawl(self):
        """Why `seen` cannot be the number pagination asks.

        A full page the parser only partly understands is still a full page.
        Counting the read offers and then stopping when *that* falls short of
        `PER_PAGE` would truncate the crawl at the first page carrying a
        promoted slot — which is most of them.
        """
        full_page = kariera_page(
            *(kariera_offer(i) for i in range(kariera.PER_PAGE - 1)),
            kariera_offer(98, href="/redirect.php?id=98"),
            # A banner slot is not a row the board served at all — it has never
            # counted towards a page being full, and must not start now.
            kariera_offer(99, classes="offer highlight"),
        )
        pages = []

        def serve(url):
            pages.append(url)
            return full_page if len(pages) == 1 else kariera_page(kariera_offer(500))

        ctx = RecordingContext()
        with mock.patch.object(kariera, "http_get", side_effect=serve):
            stubs = kariera.KarieraSource()._search_term("python", 7, set(), ctx)

        self.assertEqual(len(pages), 2, "a promoted slot is not the end of the results")
        self.assertEqual(ctx.seen_counts, [kariera.PER_PAGE - 1, 1],
                         "and the alarm is still told only what was read")
        self.assertEqual(len(stubs), kariera.PER_PAGE)


# ── Asking the board for a place, instead of filtering its answer ────

def jobicy_feed(*ids):
    import json
    return json.dumps({"jobs": [
        {"id": i, "jobTitle": "Python developer", "companyName": "ACME",
         "jobGeo": "Europe", "url": f"https://jobicy.com/jobs/{i}",
         "jobDescription": "<p>Python.</p>", "pubDate": "2026-08-20 09:00:00",
         "jobLevel": "Senior", "jobType": ["full_time"]}
        for i in ids
    ]})


class JobicyGeoTests(unittest.TestCase):
    """The one board of the six that takes a geography in the request.

    What these pin is not "the URL has a parameter on it" but the rule around
    it: narrowing happens only when it is genuinely a narrowing for *everyone*
    the shared crawl serves, and the fallback is the unfiltered feed the
    adapter has always fetched — never an empty one.
    """

    def search(self, regions):
        source = jobicy.JobicySource()
        ctx = RecordingContext(regions=regions)
        urls = []

        def fake_get(url, **kwargs):
            urls.append(url)
            return jobicy_feed(len(urls))

        with mock.patch.object(jobicy, "http_get", side_effect=fake_get):
            stubs = source.search(None, ["python"], 3650, set(), ctx)
        return urls, stubs, ctx

    def test_a_european_crawl_asks_the_board_for_europe(self):
        urls, stubs, ctx = self.search({"SK", "EU"})
        self.assertEqual(len(urls), 1)
        self.assertIn("geo=europe", urls[0])
        self.assertIn("tag=python", urls[0], "the term is still asked for")
        self.assertEqual(len(stubs), 1, "and the answer is parsed as before")
        self.assertIn("Europe", ctx.phases[0], "the progress line says where")

    def test_narrowing_never_costs_a_second_pass(self):
        """One geo or none: Jobicy rate-limits, so a term is one request."""
        for regions in ({"SK"}, {"AU"}, {"BR"}, set()):
            urls, _, _ = self.search(regions)
            self.assertEqual(len(urls), 1, regions)

    def test_a_crawl_that_spans_regions_asks_for_everything(self):
        for regions in ({"SK", "US"}, {"CA"}, {"ANY"}, {"SK", "IL"}):
            urls, stubs, _ = self.search(regions)
            self.assertNotIn("geo=", urls[0], regions)
            self.assertEqual(len(stubs), 1, "the unfiltered feed, not an empty one")

    def test_an_unplaceable_instance_is_the_old_behaviour_exactly(self):
        """No users to narrow for is the state every instance shipped in."""
        urls, _, ctx = self.search(set())
        self.assertEqual(urls, [jobicy.API_URL.format(term="python")])
        self.assertNotIn(" in ", ctx.phases[0])

    def test_every_slug_it_can_send_was_one_we_checked(self):
        """`GEO` is a list of slugs tried against the live API — an unknown one
        is a 400 there, so a guess would take the board out of the scan."""
        self.assertTrue(set(jobicy.GEO) <= set(places.REGION_MEMBERS))
        self.assertNotIn("NA", jobicy.GEO, "the board has no North America slug")


class OtherBoardsIgnoreRegionsTests(unittest.TestCase):
    """The other three feeds take no geography, and must not pretend to.

    Remotive and Arbeitnow accept unknown query parameters and answer as if
    they were absent, so a narrowing guessed at rather than confirmed would
    look like it worked and quietly do nothing. The adapters therefore send no
    geography at all, and this is the test that says so out loud.
    """

    def test_the_worldwide_feeds_send_no_geography(self):
        for module in (remoteok, remotive, arbeitnow):
            self.assertNotIn("geo=", module.API_URL, module.__name__)

    def test_a_narrowed_crawl_changes_nothing_about_their_request(self):
        source = remotive.RemotiveSource()
        urls = []

        def fake_get(url, **kwargs):
            urls.append(url)
            return '{"jobs": []}'

        for regions in (set(), {"SK", "EU"}):
            with mock.patch.object(remotive, "http_get", side_effect=fake_get):
                source.search(None, ["python"], 7, set(), RecordingContext(regions=regions))
        self.assertEqual(urls[0], urls[1], "same request, narrowed or not")


class RemotiveIsReadOnceTests(unittest.TestCase):
    """The feed *is* the board, so it is read once a scan, not once a term.

    Measured against the live API on 2026-09-22 and again on 2026-09-23:
    `search=python`, `search=developer`, `search=zzqqxxnonsense`,
    `category=software-dev`, `limit=5`, `limit=500` and the bare URL all
    return the same eighteen ids, and the payload's own `job-count` and
    `total-job-count` both say 18 — there is nothing a request can narrow
    towards. The board's `0-legal-notice` then asks for "max. 4 times a day …
    excessive requests will be blocked", and asking per term made nineteen
    requests a scan on the default profile — seventy-six a day — to be handed
    the same eighteen jobs nineteen times.
    """

    TERMS = ["python", "developer", "vývojár", "frontend"]

    def feed(self, *jobs):
        return json.dumps(
            {"job-count": len(jobs), "total-job-count": len(jobs), "jobs": list(jobs)}
        )

    def job(self, job_id=1, title="Senior Python developer", **extra):
        item = {
            "id": job_id,
            "title": title,
            "company_name": "ACME",
            "candidate_required_location": "Europe",
            "publication_date": "2026-09-18T10:00:00",
            "url": f"https://remotive.com/remote-jobs/{job_id}",
            "description": "<p>Python and SQL</p>",
        }
        item.update(extra)
        return item

    def search(self, body, terms=None, days=0, known=None):
        urls = []
        ctx = RecordingContext()

        def fake_get(url, **kwargs):
            urls.append(url)
            return body

        with mock.patch.object(remotive, "http_get", side_effect=fake_get):
            stubs = remotive.RemotiveSource().search(
                None, terms or self.TERMS, days,
                set() if known is None else known, ctx,
            )
        return urls, stubs, ctx

    def test_four_search_terms_are_still_one_request(self):
        urls, _, _ = self.search(self.feed(self.job()))
        self.assertEqual(len(urls), 1, "one request per scan, whatever the terms")

    def test_the_request_carries_no_query_parameters_at_all(self):
        """Every one of them is ignored, so sending one is a claim we cannot
        make — the same rule that keeps a geography off this URL."""
        urls, _, _ = self.search(self.feed(self.job()))
        self.assertNotIn("?", urls[0], urls[0])

    def test_the_terms_now_filter_here_instead_of_in_the_request(self):
        """Nothing asks the board for the term any more, so dropping the local
        match would quietly import the whole feed."""
        _, stubs, _ = self.search(self.feed(
            self.job(1, "Senior Python developer"),
            self.job(2, "Head of Sales"),
        ))
        self.assertEqual([s["source_id"] for s in stubs], ["1"])

    def test_tags_still_count_towards_a_match(self):
        _, stubs, _ = self.search(self.feed(
            self.job(3, "Backend engineer", tags=["python", "aws"]),
        ))
        self.assertEqual([s["source_id"] for s in stubs], ["3"])

    def test_seen_is_reported_once_and_is_the_board_s_own_number(self):
        """Per term, the alarm was told 18 × 19 = 342 for a board showing 18."""
        _, _, ctx = self.search(self.feed(self.job(1), self.job(2, "Head of Sales")))
        self.assertEqual(ctx.seen_counts, [2])

    def test_seen_counts_rows_it_could_read_not_the_length_of_the_array(self):
        """A feed that still serves rows the parser can no longer read is the
        silent redesign `seen` exists to catch — an array length cannot fail."""
        _, _, ctx = self.search(self.feed(
            self.job(1),
            self.job(2, title=""),          # no title
            {"title": "No id at all"},      # no id
            "not even an object",
        ))
        self.assertEqual(ctx.total_seen, 1)

    def test_already_known_ids_are_still_listings_the_board_showed_us(self):
        _, stubs, ctx = self.search(self.feed(self.job(1)), known={"1"})
        self.assertEqual((stubs, ctx.total_seen), ([], 1))

    def test_a_failed_fetch_is_the_source_failing_and_says_so(self):
        """With one request there is no "other terms might work" left, so this
        raises and the scan records a source error — which is also what stops
        the silent-board alarm adding a vaguer complaint on top of it."""
        with mock.patch.object(remotive, "http_get", side_effect=OSError("503")):
            with self.assertRaises(OSError):
                remotive.RemotiveSource().search(
                    None, self.TERMS, 0, set(), RecordingContext()
                )


# ── The Czech board ──────────────────────────────────────────

def jobscz_card(job_id, title="Python developer", status="25. srpna",
                tag="", locality="Praha – Nové Město", company="ACME s.r.o."):
    return f"""
      <article class="SearchResultCard">
        <header class="SearchResultCard__header">
          <h2 class="SearchResultCard__title">
            <a class="SearchResultCard__titleLink" data-jobad-id="{job_id}"
               href="https://www.jobs.cz/rpd/{job_id}/?searchId=abc">{title}</a>
          </h2>
          <div class="SearchResultCard__status">{status}</div>
        </header>
        <div class="SearchResultCard__body">{tag}</div>
        <footer class="SearchResultCard__footer">
          <ul class="SearchResultCard__footerList">
            <li class="SearchResultCard__footerItem">{company}</li>
            <li class="SearchResultCard__footerItem">
              <span data-test="serp-locality">{locality}</span></li>
            <li class="SearchResultCard__footerItem">
              <span data-test="serp-atmoskop">242 hodnocení na Atmoskopu</span></li>
          </ul>
        </footer>
      </article>
    """


def jobscz_page(*cards):
    return "<html><body>" + "".join(cards) + "</body></html>"


TAG_REMOTE = '<span class="Tag">Práce převážně z domova</span>'
TAG_HYBRID = '<span class="Tag">Možnost občasné práce z domova</span>'
TAG_SALARY = '<span class="Tag">70 000 \u200d–\u200d 85 000 Kč</span>'


class JobsCzParseTests(unittest.TestCase):
    def test_a_normal_page_yields_stubs(self):
        html = jobscz_page(jobscz_card("1"), jobscz_card("2", title="Python analytik"))
        stubs, seen = jobscz.parse_cards(html, set())

        self.assertEqual(seen, 2)
        self.assertEqual([s["source_id"] for s in stubs], ["1", "2"])
        self.assertEqual(stubs[0]["company"], "acme s.r.o.")
        self.assertEqual(stubs[0]["location"], "praha – nové město")
        self.assertEqual(stubs[0]["link"], "https://www.jobs.cz/rpd/1/",
                         "the tracking query string is not part of the job's identity")

    def test_ads_we_already_have_still_count_as_listings(self):
        """The distinction the whole `seen` contract exists for."""
        html = jobscz_page(jobscz_card("1"), jobscz_card("2"))
        stubs, seen = jobscz.parse_cards(html, {"1", "2"})

        self.assertEqual(stubs, [], "nothing new")
        self.assertEqual(seen, 2, "but the board did show us two")

    def test_a_page_this_parser_cannot_read_lists_nothing(self):
        stubs, seen = jobscz.parse_cards("<html><body><div>redesign</div></body></html>", set())
        self.assertEqual((stubs, seen), ([], 0))

    def test_a_card_whose_title_link_moved_is_not_counted_as_read(self):
        broken = jobscz_card("1").replace("SearchResultCard__titleLink", "somethingElse")
        stubs, seen = jobscz.parse_cards(jobscz_page(broken, jobscz_card("2")), set())

        self.assertEqual(seen, 1, "a half-redesign must still trip the alarm")
        self.assertEqual([s["source_id"] for s in stubs], ["2"])

    def test_the_company_is_not_the_locality_or_the_rating(self):
        """All three sit in the same footer list; only the company has no data-test."""
        stubs, _ = jobscz.parse_cards(jobscz_page(jobscz_card("1")), set())
        self.assertEqual(stubs[0]["company"], "acme s.r.o.")

    def test_extra_localities_are_a_count_and_not_a_place(self):
        html = jobscz_page(jobscz_card("1", locality="Brno – Starý Lískovec + 1 další lokalita"))
        stubs, _ = jobscz.parse_cards(html, set())
        self.assertEqual(stubs[0]["location"], "brno – starý lískovec")
        self.assertEqual(places.codes("jobscz", stubs[0]["location"]), ("CZ",))

    def test_the_work_from_home_tags_become_a_worktype(self):
        html = jobscz_page(jobscz_card("1", tag=TAG_REMOTE),
                           jobscz_card("2", tag=TAG_HYBRID),
                           jobscz_card("3"))
        stubs, _ = jobscz.parse_cards(html, set())
        self.assertEqual([s["worktype"] for s in stubs], ["remote", "hybrid", None],
                         "the board states remote and hybrid and never states on-site, "
                         "so an absent tag is silence and stays unknown")

    def test_a_salary_tag_is_read_and_a_recruitment_tag_is_not(self):
        noise = '<span class="Tag">Odpověď do 2 týdnů</span>'
        html = jobscz_page(jobscz_card("1", tag=noise + TAG_SALARY))
        stubs, _ = jobscz.parse_cards(html, set())
        self.assertEqual(salary.parse_salary(stubs[0]["salary"]),
                         (70000.0, 85000.0, "CZK", "month"))

    def test_an_expiry_countdown_is_never_read_as_a_posting_date(self):
        """"Končí za 3 dny" is a deadline; dating a job by it is off by its whole life."""
        html = jobscz_page(jobscz_card("1", status="Končí za 8 hodin"),
                           jobscz_card("2", status="Končí zítra"),
                           jobscz_card("3", status="Přidáno včera"))
        stubs, _ = jobscz.parse_cards(html, set())
        self.assertEqual([s["freshness"] for s in stubs][:2], [None, None])
        self.assertIsNotNone(stubs[2]["posted_at"])


class JobsCzWindowTests(unittest.TestCase):
    """The board takes three windows and treats a fourth as *no filter at all*.

    Measured live: 24h/3d/7d cut a 282-result search to 23/74/139, while 1d,
    2d, 4d, 14d, 30d, 1m, 1w and a nonsense `99z` all returned the full 282.
    So a window it does not know is not an error, it is the entire board — the
    same silent-acceptance trap Remotive has, and the reason the roadmap says
    an unconfirmed parameter is worse than none.
    """

    def test_only_windows_the_board_was_shown_to_honour_are_sent(self):
        self.assertEqual(
            [jobscz._date_step(d) for d in (1, 2, 3, 5, 7)],
            ["24h", "3d", "3d", "7d", "7d"])

    def test_a_window_wider_than_the_board_understands_asks_for_everything(self):
        for days in (8, 14, 30, 365):
            self.assertIsNone(jobscz._date_step(days))
            self.assertNotIn("date=", jobscz._search_url("python", days, 1))

    def test_every_token_it_can_send_was_one_we_measured(self):
        sent = {jobscz._date_step(d) for d in range(1, 40)} - {None}
        self.assertEqual(sent, {token for _, token in jobscz.DATE_STEPS})

    def test_the_first_page_carries_no_page_parameter(self):
        self.assertNotIn("page=", jobscz._search_url("python", 7, 1))
        self.assertIn("page=2", jobscz._search_url("python", 7, 2))


class JobsCzSearchTests(unittest.TestCase):
    def search(self, pages, days=7, known=None):
        source = jobscz.JobsCzSource()
        ctx = RecordingContext()
        self.urls = []

        def fake_get(url, **kwargs):
            self.urls.append(url)
            return pages[min(len(self.urls) - 1, len(pages) - 1)]

        with mock.patch.object(jobscz, "http_get", side_effect=fake_get):
            stubs = source._search_term("python", days, known if known is not None else set(), ctx)
        return stubs, ctx

    def test_a_short_page_is_the_last_page(self):
        stubs, ctx = self.search([jobscz_page(*(jobscz_card(str(i)) for i in range(3)))])
        self.assertEqual(len(self.urls), 1, "three cards is not a full page of thirty")
        self.assertEqual(ctx.total_seen, 3)
        self.assertEqual(len(stubs), 3)

    def test_a_full_page_is_followed_by_the_next_one(self):
        full = jobscz_page(*(jobscz_card(str(i)) for i in range(jobscz.PER_PAGE)))
        short = jobscz_page(jobscz_card("999"))
        stubs, ctx = self.search([full, short])
        self.assertEqual(len(self.urls), 2)
        self.assertIn("page=2", self.urls[1])
        self.assertEqual(len(stubs), jobscz.PER_PAGE + 1)

    def test_a_board_that_never_runs_out_is_capped(self):
        full = jobscz_page(*(jobscz_card(str(i)) for i in range(jobscz.PER_PAGE)))
        with mock.patch.object(jobscz, "MAX_PAGES", 3):
            stubs, ctx = self.search([full])
        self.assertEqual(len(self.urls), 3)

    def test_a_term_that_fails_is_reported_and_not_silence(self):
        source = jobscz.JobsCzSource()
        ctx = RecordingContext()
        with mock.patch.object(jobscz, "http_get", side_effect=OSError("503")):
            stubs = source._search_term("python", 7, set(), ctx)
        self.assertEqual(stubs, [])
        self.assertEqual(len(ctx.warnings), 1,
                         "a board answering 503 must not read as a board with no jobs")

    def test_it_sends_no_geography(self):
        """No confirmed geography parameter exists, and the board is Czech anyway."""
        source = jobscz.JobsCzSource()
        urls = []

        def fake_get(url, **kwargs):
            urls.append(url)
            return jobscz_page()

        for regions in (set(), {"SK", "EU"}):
            with mock.patch.object(jobscz, "http_get", side_effect=fake_get):
                source.search(None, ["python"], 7, set(), RecordingContext(regions=regions))
        self.assertEqual(urls[0], urls[1], "same request, narrowed or not")


MICROSITE_HTML = "<html><body><div id='widget_container'></div></body></html>"


class WidgetNode:
    def __init__(self, text):
        self._text = text

    def inner_text(self):
        return self._text


class MicrositePage:
    """A Playwright page that hands out whatever the widget has rendered so far.

    `texts` is what `#capybara-position-detail` contains on each successive
    look — None for "not mounted yet" — which is how the skeleton is modelled.
    """

    def __init__(self, texts):
        self.texts = list(texts)
        self.goto_urls = []
        self.waits = 0

    def goto(self, url, **kwargs):
        self.goto_urls.append(url)

    def query_selector(self, selector):
        assert selector == jobscz.WIDGET_SELECTOR, selector
        text = self.texts[min(self.waits, len(self.texts) - 1)]
        return WidgetNode(text) if text is not None else None

    def wait_for_timeout(self, ms):
        self.waits += 1


class JobsCzDetailTests(unittest.TestCase):
    """One link, two boards. See the adapter's docstring: `www.jobs.cz/rpd/<id>/`
    redirects either to jobs.cz's own server-rendered ad view or to the
    employer's microsite, where the body only exists after JavaScript. Measured
    over 30 live ads across two terms: 21 hosted, 9 microsite.
    """

    def detail(self, html, page=None):
        with mock.patch.object(jobscz, "http_get", return_value=html):
            return jobscz.JobsCzSource().fetch_detail(page, "https://www.jobs.cz/rpd/1/")

    def test_the_hosted_ad_body_is_read_over_plain_http(self):
        html = ('<html><body><div data-test="jd-body-richtext">'
                '<p>You will   build   things.</p></div></body></html>')
        self.assertEqual(self.detail(html), "You will build things.")

    def test_a_hosted_page_never_touches_the_browser(self):
        """Seven ads in ten, and paying for a page render on them would be waste."""
        page = MicrositePage(["irrelevant" * 50])
        html = '<html><body><div data-test="jd-body-richtext">Real body.</div></body></html>'
        self.assertEqual(self.detail(html, page), "Real body.")
        self.assertEqual(page.goto_urls, [], "the browser was not asked")

    def test_a_microsite_is_read_through_the_browser(self):
        body = "Budete stavět věci. " * 20
        page = MicrositePage([body])
        self.assertEqual(self.detail(MICROSITE_HTML, page), body.strip())
        self.assertEqual(len(page.goto_urls), 1)

    def test_the_widget_skeleton_is_not_mistaken_for_the_ad(self):
        """It mounts the container empty and fills it a moment later: waiting on
        the element alone returned 11 characters against real bodies of 2 800+,
        and storing that is a job that scores on nothing and is never retried."""
        body = "The actual posting. " * 20
        page = MicrositePage([None, "Načítání…", body])
        self.assertEqual(self.detail(MICROSITE_HTML, page), body.strip())

    def test_a_widget_that_never_fills_is_a_failed_read_not_a_short_one(self):
        page = MicrositePage(["Načítání…"])
        self.assertEqual(self.detail(MICROSITE_HTML, page), "")
        self.assertEqual(page.waits, jobscz.WIDGET_POLLS, "it gave the widget its full budget")

    def test_a_microsite_with_no_browser_reads_as_empty_rather_than_raising(self):
        self.assertEqual(self.detail(MICROSITE_HTML), "")

    def test_a_page_without_a_body_reads_as_empty_rather_than_raising(self):
        self.assertEqual(self.detail("<html><body></body></html>"), "")


class JobsCzRegistrationTests(unittest.TestCase):
    """Adding a board is one file and a registry entry — plus the two places
    that decide what it is *about*, which are easy to add a board without."""

    def test_the_board_is_registered_and_declares_the_browser_it_needs(self):
        """`needs_browser` is about the detail pages only — but it is declared
        rather than improvised, because otherwise the three microsite ads in ten
        would be read only when profesia happened to be enabled as well."""
        from jobmatch.sources import SOURCES
        self.assertIs(SOURCES["jobscz"].__class__, jobscz.JobsCzSource)
        self.assertTrue(SOURCES["jobscz"].needs_browser)

    def test_search_works_without_the_page_it_is_handed(self):
        source = jobscz.JobsCzSource()
        with mock.patch.object(jobscz, "http_get", return_value=jobscz_page(jobscz_card("1"))):
            stubs = source.search(None, ["python"], 7, set(), RecordingContext())
        self.assertEqual([s["source_id"] for s in stubs], ["1"])

    def test_it_is_on_by_default(self):
        from jobmatch import db
        self.assertIn("jobscz", db.DEFAULT_SETTINGS["enabled_sources"])

    def test_an_unplaceable_czech_town_is_still_czech(self):
        self.assertEqual(places.codes("jobscz", "nějaká vesnice"), ("CZ",))

    def test_provides_matches_what_the_adapter_actually_sets(self):
        """`reextract` trusts this declaration to know what it must not overwrite."""
        stubs, _ = jobscz.parse_cards(jobscz_page(jobscz_card("1", tag=TAG_REMOTE)), set())
        supplied = {k for k in ("worktype", "seniority", "employment_type") if k in stubs[0]}
        self.assertEqual(supplied, set(jobscz.JobsCzSource.provides))


if __name__ == "__main__":
    unittest.main()

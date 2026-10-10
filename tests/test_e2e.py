"""Phase 8: the whole loop, through the doors a browser actually uses.

signup → settings → queue a scan → **the worker** runs it → the jobs arrive
scored → triage one as applied → it is in the tracker → walk it down the
pipeline. Every other suite here tests one seam and most of them turn CSRF off
and call the internals directly, which is right for a unit test and is exactly
what an end-to-end test may not do. So this one keeps CSRF **on** and carries
the token the way `app.js` does, and it never calls `scan._run_scan`: the scan
is started by `worker.run(once=True)` on the worker's own connection, because
the web tier only ever enqueues and a test that scanned inside the request
would be exercising a path that does not exist in production.

The board is a fake in the `SOURCES` registry, so there is no network, no
politeness delay and no Playwright. What is under test is the wiring — signup,
the queue, the worker, extraction, scoring, the tracker — not anybody's HTML.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import unittest

import config
from jobmatch import db, scan, worker
from jobmatch.sources import SOURCES
from jobmatch.sources.base import JobSource

# The harness, and `webapp` through it rather than by importing `app` here:
# `app` reads its config at import time, and switching rate limiting off has to
# happen before that. test_auth is where that ordering is written down, so
# taking the module from it is what keeps this file from re-deciding it.
from tests.test_auth import PASSWORD, AuthTestCase, webapp

# The two offers the fake board has. One is everything the user asked for and
# one is nothing they asked for, so the score is an assertion and not a shrug:
# the first scores 100 on all four components, the second 0 on all four.
OFFERS = {
    "match": {
        "title": "Senior Python developer",
        "company": "ACME",
        "location": "Bratislava",
        "description": (
            "Senior Python developer. Django, React. "
            "Práca z domu, plný úväzok."
        ),
    },
    "miss": {
        "title": "Junior Java developer",
        "company": "Other s.r.o.",
        "location": "Košice",
        "description": "Junior Java developer. Java, Spring. Práca v kancelárii.",
    },
}


class FakeBoard(JobSource):
    """One board, two offers, answered from memory.

    Deliberately a *detail-page* board — the listing carries no description and
    `fetch_detail` supplies it — because that is the shape profesia and kariéra
    have, and it is the only shape that walks the enrich phase, which is where
    the description, and with it every extracted skill, actually arrives.
    """

    name = "fake"
    label = "Fake board"
    needs_browser = False

    def __init__(self):
        self.detail_fetches = 0

    def search(self, page, terms, days, known_ids, ctx):
        ctx.progress(f"Searching {self.label}")
        ctx.seen(len(OFFERS))   # what the board showed us, matched or not
        return [
            {
                "source_id": key, "title": offer["title"], "company": offer["company"],
                "location": offer["location"], "salary": "2000 - 3000 EUR/mesiac",
                "freshness": "pred 1 dňom", "link": f"https://example.test/{key}",
            }
            for key, offer in OFFERS.items()
            if key not in known_ids
        ]

    def fetch_detail(self, page, url):
        self.detail_fetches += 1
        return OFFERS[url.rsplit("/", 1)[-1]]["description"]


class Browser:
    """A test client that carries its CSRF token the way the pages do.

    Two tokens, because the app has two paths: the hidden field a `<form>`
    posts, and the `<meta>` tag `app.js` reads and sends as `X-CSRFToken` on
    every fetch. A test that only used one would leave the other unexercised.
    """

    def __init__(self):
        self.client = webapp.app.test_client()

    def form_token(self, path):
        page = self.client.get(path).get_data(as_text=True)
        return page.split('name="csrf_token" value="')[1].split('"')[0]

    def header_token(self, path="/jobs"):
        page = self.client.get(path).get_data(as_text=True)
        return page.split('name="csrf-token" content="')[1].split('"')[0]

    def signup(self, email, password=PASSWORD):
        return self.client.post("/signup", data={
            "email": email, "password": password, "confirm": password,
            "csrf_token": self.form_token("/signup"),
        })

    def send(self, method, path, payload=None):
        """A JSON call with the token, i.e. what the page's JS would send."""
        return getattr(self.client, method)(
            path, json=payload, headers={"X-CSRFToken": self.header_token()},
        )

    def get_json(self, path):
        return self.client.get(path).get_json()


class EndToEndTestCase(AuthTestCase):
    """The real app, the real token, a fake board and no sleeping."""

    csrf = True

    def setUp(self):
        super().setUp()
        self._e2e_orig = (
            config.SCAN_ENABLED, config.SCAN_INTERVAL_HOURS,
            config.MIN_PAGE_DELAY, config.MAX_PAGE_DELAY,
            config.MIN_DETAIL_DELAY, config.MAX_DETAIL_DELAY,
        )
        config.SCAN_ENABLED = True
        # The schedule is off: this suite queues its scans deliberately, and a
        # worker pass that also decided one was due would blur which is which.
        config.SCAN_INTERVAL_HOURS = 0
        # The politeness delays are real and are staying — but they are about
        # somebody else's server, and this board is a dict.
        config.MIN_PAGE_DELAY = config.MAX_PAGE_DELAY = 0
        config.MIN_DETAIL_DELAY = config.MAX_DETAIL_DELAY = 0

        self.board = FakeBoard()
        SOURCES[self.board.name] = self.board
        worker._shutdown.clear()

    def tearDown(self):
        SOURCES.pop(self.board.name, None)
        worker._shutdown.clear()
        (
            config.SCAN_ENABLED, config.SCAN_INTERVAL_HOURS,
            config.MIN_PAGE_DELAY, config.MAX_PAGE_DELAY,
            config.MIN_DETAIL_DELAY, config.MAX_DETAIL_DELAY,
        ) = self._e2e_orig
        super().tearDown()

    def run_the_worker(self):
        """One pass of the process that scrapes — its own entrypoint, its own
        connection, exactly as the worker container starts it."""
        worker.run(once=True)


class WholeLoopTests(EndToEndTestCase):
    def test_a_stranger_can_sign_up_scan_and_track_an_application(self):
        browser = Browser()

        # 1. The front page greets a stranger rather than asking them to log in.
        landing = browser.client.get("/")
        self.assertEqual(landing.status_code, 200)
        self.assertIn("scored against your CV", landing.get_data(as_text=True))

        # 2. Signing up lands on Settings, which is where a new account has
        #    something to do. First account in, so it owns the instance.
        res = browser.signup("first@example.com")
        self.assertEqual(res.status_code, 302, "signup did not redirect — it failed")
        self.assertIn("/settings", res.headers["Location"])
        user_id = db.get_user_by_email(self.conn, "first@example.com")["id"]
        self.assertTrue(
            self.conn.scalar("SELECT is_admin FROM users WHERE id = :id", {"id": user_id}),
            "the first account has to be able to trigger the crawl",
        )

        # 3. They tell it who they are and which boards to read. Through the
        #    route, so the weight normalization and the source whitelist run.
        saved = browser.send("put", "/api/settings", {
            "enabled_sources": ["fake", "not-a-board"],
            "search_terms": ["python"],
            "user_skills": ["Python", "django", "react"],
            "user_location": "Bratislava",
            "user_worktype": "remote",
            "user_seniority": "senior",
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json()["saved"]["enabled_sources"], ["fake"],
                         "a board nobody has heard of must not be storable")

        # 4. Starting a scan queues one. It does not run one: the web process
        #    never scrapes, which is the whole of Phase 4 in one assertion.
        started = browser.send("post", "/api/scan/start")
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.get_json()["status"], "queued")
        self.assertEqual(browser.get_json("/api/scan/status")["status"], "queued")
        self.assertEqual(self.conn.scalar("SELECT COUNT(*) FROM jobs"), 0,
                         "the web process scraped something — it must not")

        # 5. The worker picks it up.
        self.run_the_worker()

        status = browser.get_json("/api/scan/status")
        self.assertEqual(status["status"], "done")
        self.assertEqual(status["found"], len(OFFERS))
        self.assertEqual(status["enriched"], len(OFFERS), "both descriptions were read")
        self.assertEqual(status["source_errors"], {},
                         "a board that answered must not be accused of silence")
        self.assertEqual(self.board.detail_fetches, len(OFFERS))

        # 6. The jobs are in the user's list, extracted and scored — and the
        #    two ends of the score are the ones the offers were written for.
        listing = browser.get_json("/api/jobs?sort=score")
        self.assertEqual(listing["total"], len(OFFERS))
        top, bottom = listing["jobs"][0], listing["jobs"][-1]
        self.assertEqual(top["title"], OFFERS["match"]["title"])
        self.assertEqual(top["match_score"], 100.0)
        self.assertEqual(top["worktype"], "remote", "extraction ran on the fetched text")
        self.assertIn("python", top["skills"])
        # The Java ad is not this person's job and must not count as a match.
        # It is no longer a flat zero: its title does say "developer", which
        # the role component scores on its lowest rung — the exact arithmetic
        # is pinned in test_scoring.py, what matters here is that it stays well
        # under the threshold while the Python ad is a perfect fit.
        self.assertLess(bottom["match_score"], db.DEFAULT_SETTINGS["min_match_score"])
        self.assertLess(bottom["match_score"], top["match_score"])
        # The scan placed the job as it stored it: "Bratislava" is a town on a
        # board, and `jobs.country` is what the Jobs page filters on.
        self.assertEqual(top["country"], "SK")
        self.assertEqual(top["country_label"], "Slovakia")

        stats = browser.get_json("/api/stats")
        self.assertEqual(stats["matched"], 1, "one of the two is above the threshold")
        self.assertEqual(stats["unscored"], 0, "both descriptions arrived")

        # 7. The list deliberately omits the description — nowhere surfaces it.
        self.assertNotIn("description", top)

        # 8. Applying to it opens a tracker entry — one act, two records.
        applied = browser.send("post", f"/api/jobs/{top['id']}/status",
                               {"status": "applied"})
        self.assertEqual(applied.status_code, 200)

        tracker = browser.get_json("/api/applications")
        self.assertEqual(tracker["count"], 1)
        entry = tracker["applications"][0]
        self.assertEqual(entry["job_id"], top["id"])
        self.assertEqual(entry["status"], "applied")
        self.assertEqual(entry["match_score"], 100.0, "the tracker keeps the score")

        # 9. And it walks down the pipeline, leaving history behind it.
        for to_status in ("interview", "offer"):
            res = browser.send("patch", f"/api/applications/{entry['id']}",
                               {"status": to_status, "note": f"moved to {to_status}"})
            self.assertEqual(res.status_code, 200)

        entry = browser.get_json("/api/applications")["applications"][0]
        self.assertEqual(entry["status"], "offer")
        self.assertEqual([e["to_status"] for e in entry["events"]], ["offer", "interview"],
                         "newest first, and nothing was overwritten")

        # 10. Every page the user has just been through still renders.
        for path in ("/", "/jobs", "/tracker", "/settings"):
            self.assertEqual(browser.client.get(path).status_code, 200, path)
        self.assertEqual(browser.get_json("/api/stats")["applied"], 1)

    def test_a_second_scan_finds_nothing_new_and_says_nothing_is_wrong(self):
        """The false positive the whole `seen`/`warn` mechanism exists to avoid,
        from the outside: the second scan of an unchanged board is a quiet
        success, not a broken adapter — and it re-reads no descriptions."""
        browser = Browser()
        browser.signup("first@example.com")
        browser.send("put", "/api/settings", {"enabled_sources": ["fake"]})

        browser.send("post", "/api/scan/start")
        self.run_the_worker()
        browser.send("post", "/api/scan/start")
        self.run_the_worker()

        status = browser.get_json("/api/scan/status")
        self.assertEqual(status["status"], "done")
        self.assertEqual(status["found"], 0, "it already had both")
        self.assertEqual(status["source_errors"], {}, "a quiet day is not a broken board")
        self.assertEqual(self.conn.scalar("SELECT COUNT(*) FROM jobs"), len(OFFERS),
                         "the pool must not have grown a duplicate")
        self.assertEqual(self.board.detail_fetches, len(OFFERS),
                         "a description already stored is never fetched twice")

    def test_a_user_who_arrives_after_the_scan_still_gets_the_pool(self):
        """The shared crawl, from the second user's side: they sign up into a
        pool that was scraped before they existed and get their own scores."""
        admin = Browser()
        admin.signup("first@example.com")
        admin.send("put", "/api/settings", {
            "enabled_sources": ["fake"],
            "user_skills": ["python", "django", "react"],
            "user_location": "Bratislava",
            "user_worktype": "remote",
            "user_seniority": "senior",
        })
        admin.send("post", "/api/scan/start")
        self.run_the_worker()

        latecomer = Browser()
        latecomer.signup("second@example.com")
        latecomer.send("put", "/api/settings", {
            "user_skills": ["java", "spring"],
            "user_location": "Košice",
            "user_worktype": "onsite",
            "user_seniority": "junior",
        })

        theirs = latecomer.get_json("/api/jobs?sort=score")
        self.assertEqual(theirs["total"], len(OFFERS), "the pool is shared")
        self.assertEqual(theirs["jobs"][0]["title"], OFFERS["miss"]["title"],
                         "the same two jobs, ranked for a different person")
        # A strong match for them — the ad names their language in its title,
        # their level and their town. Not a perfect 100: the ad lists two
        # skills, and covering a two-item list is thinner evidence than
        # covering a full stack (see `SkillsEvidenceTests`).
        self.assertGreater(theirs["jobs"][0]["match_score"],
                           theirs["jobs"][-1]["match_score"])
        self.assertGreaterEqual(theirs["jobs"][0]["match_score"], 80.0)

        # And the admin's own ranking did not move a point.
        self.assertEqual(
            admin.get_json("/api/jobs?sort=score")["jobs"][0]["title"],
            OFFERS["match"]["title"],
        )
        self.assertEqual(latecomer.get_json("/api/applications")["count"], 0)


class ScanPermissionTests(EndToEndTestCase):
    """Who may start the shared crawl, over the wire and with a real token."""

    def test_a_regular_user_cannot_start_one(self):
        Browser().signup("first@example.com")     # takes the admin slot
        regular = Browser()
        regular.signup("second@example.com")

        res = regular.send("post", "/api/scan/start")
        self.assertEqual(res.status_code, 403)
        self.assertIn("admin", res.get_json()["error"])
        self.assertIsNone(scan.current_status(self.conn), "nothing was queued")

    def test_a_scan_without_a_token_is_refused(self):
        browser = Browser()
        browser.signup("first@example.com")

        res = browser.client.post("/api/scan/start")   # no X-CSRFToken

        self.assertEqual(res.status_code, 400)
        self.assertIsNone(scan.current_status(self.conn), "nothing was queued")


if __name__ == "__main__":
    unittest.main()

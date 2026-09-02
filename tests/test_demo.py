"""Tests for Phase 7's demo account: seeding, the nightly reset, and its limits.

The demo is the only account a stranger can drive, so the interesting
assertions are the ones about what it *cannot* do and about the reset putting
back exactly what it found — a demo that drifts is a demo that eventually shows
somebody an empty tracker.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import re
import unittest
from pathlib import Path

import config
from jobmatch import auth, db, demo, display, worker
from tests.test_auth import PASSWORD, AuthTestCase, webapp


class DemoTestCase(AuthTestCase):
    """A pool worth seeding against, with DEMO_MODE on for the duration."""

    def setUp(self):
        super().setUp()
        self._demo_mode = config.DEMO_MODE
        config.DEMO_MODE = True
        for i in range(30):
            self.add_job(
                f"React developer {i}",
                skills="react,typescript,python" if i % 2 else "react,css",
                worktype="remote" if i % 3 else "hybrid",
                seniority="medior" if i % 2 else "senior",
                location="Bratislava",
            )

    def tearDown(self):
        config.DEMO_MODE = self._demo_mode
        super().tearDown()


class SeedingTests(DemoTestCase):
    def test_a_reset_produces_a_lived_in_account(self):
        summary = demo.reset(self.conn)
        self.assertEqual(summary["applications"], len(demo.SEEDED_APPLICATIONS))
        self.assertEqual(summary["declined"], demo.DECLINED_COUNT)
        # Every job in the shared pool is the demo's to look at.
        self.assertEqual(summary["jobs"], 30)
        # And every one of them is scored, which is what the sliders demo.
        unscored = self.conn.scalar(
            "SELECT COUNT(*) FROM user_jobs WHERE user_id = :u AND match_score IS NULL",
            {"u": summary["user_id"]},
        )
        self.assertEqual(unscored, 0)

    def test_the_tracker_shows_the_whole_pipeline_with_its_history(self):
        user_id = demo.reset(self.conn)["user_id"]
        statuses = [
            row["status"]
            for row in self.conn.execute(
                "SELECT status FROM applications WHERE user_id = :u", {"u": user_id}
            )
        ]
        self.assertEqual(sorted(statuses), sorted(s for s, _, _ in demo.SEEDED_APPLICATIONS))
        # An application with no events reads as fake, so each one has at least
        # the row that says it was applied to.
        events = self.conn.scalar(
            "SELECT COUNT(*) FROM application_events WHERE user_id = :u", {"u": user_id}
        )
        self.assertGreaterEqual(events, len(demo.SEEDED_APPLICATIONS))

    def test_the_applications_are_the_jobs_the_app_would_have_recommended(self):
        """Seeded off the scored order, not off arbitrary ids."""
        user_id = demo.reset(self.conn)["user_id"]
        applied = self.conn.execute(
            """SELECT uj.match_score FROM applications a
               JOIN user_jobs uj ON uj.job_id = a.job_id AND uj.user_id = a.user_id
               WHERE a.user_id = :u""",
            {"u": user_id},
        ).fetchall()
        best_untouched = self.conn.scalar(
            "SELECT MAX(match_score) FROM user_jobs "
            "WHERE user_id = :u AND status = 'new'",
            {"u": user_id},
        )
        for row in applied:
            self.assertGreaterEqual(row["match_score"], best_untouched)

    def test_resetting_twice_leaves_exactly_what_resetting_once_did(self):
        first = demo.reset(self.conn)
        counts = self._counts(first["user_id"])
        second = demo.reset(self.conn)
        self.assertEqual(second["user_id"], first["user_id"])
        self.assertEqual(self._counts(first["user_id"]), counts)

    def test_a_reset_undoes_whatever_a_visitor_did(self):
        user_id = demo.reset(self.conn)["user_id"]
        before = self._counts(user_id)
        # A visitor plays: declines everything, moves the threshold, applies.
        self.conn.execute(
            "UPDATE user_jobs SET status = 'declined' WHERE user_id = :u", {"u": user_id}
        )
        self.conn.execute("DELETE FROM application_events WHERE user_id = :u", {"u": user_id})
        self.conn.execute("DELETE FROM applications WHERE user_id = :u", {"u": user_id})
        db.set_setting(self.conn, user_id, "min_match_score", 99)
        self.conn.commit()

        demo.reset(self.conn)
        self.assertEqual(self._counts(user_id), before)
        self.assertEqual(
            db.get_setting(self.conn, user_id, "min_match_score"),
            demo.SEEDED_SETTINGS["min_match_score"],
        )

    def test_the_account_survives_its_own_reset(self):
        """Wiping the user row would sign out whoever is reading the page."""
        user_id = demo.reset(self.conn)["user_id"]
        created = db.get_user(self.conn, user_id)["created_at"]
        demo.reset(self.conn)
        row = demo.demo_user(self.conn)
        self.assertEqual(row["id"], user_id)
        self.assertEqual(db.get_user(self.conn, user_id)["created_at"], created)
        self.assertTrue(auth.verify_password(row["password_hash"], config.DEMO_PASSWORD))

    def test_the_demo_is_never_an_admin_so_it_cannot_trigger_the_shared_crawl(self):
        user_id = demo.reset(self.conn)["user_id"]
        self.assertFalse(db.get_user(self.conn, user_id)["is_admin"])
        # And even as the only account on the box it does not take the slot.
        self.assertFalse(db.has_admin(self.conn))
        # …which is what leaves it for the first person who signs up.
        self.conn.execute("UPDATE users SET is_admin = 1 WHERE id = :id", {"id": user_id})
        self.conn.commit()
        demo.reset(self.conn)
        self.assertFalse(db.get_user(self.conn, user_id)["is_admin"])

    def _counts(self, user_id):
        scope = {"u": user_id}
        return {
            "applications": self.conn.scalar(
                "SELECT COUNT(*) FROM applications WHERE user_id = :u", scope),
            "events": self.conn.scalar(
                "SELECT COUNT(*) FROM application_events WHERE user_id = :u", scope),
            "declined": self.conn.scalar(
                "SELECT COUNT(*) FROM user_jobs WHERE user_id = :u AND status = 'declined'",
                scope),
            "applied": self.conn.scalar(
                "SELECT COUNT(*) FROM user_jobs WHERE user_id = :u AND status = 'applied'",
                scope),
            "settings": self.conn.scalar(
                "SELECT COUNT(*) FROM user_settings WHERE user_id = :u", scope),
        }


class ResetScheduleTests(DemoTestCase):
    """The schedule is a query, exactly like the scan schedule it copies."""

    def test_enabled_but_never_seeded_is_due(self):
        self.assertTrue(demo.due_for_reset(self.conn))

    def test_just_reset_is_not_due_again(self):
        demo.reset(self.conn)
        self.assertFalse(demo.due_for_reset(self.conn))

    def test_it_becomes_due_once_the_interval_has_passed(self):
        demo.reset(self.conn)
        later = display.utcnow().replace(year=display.utcnow().year + 1)
        self.assertTrue(demo.due_for_reset(self.conn, now=later))

    def test_demo_mode_off_never_resets_anything(self):
        config.DEMO_MODE = False
        self.assertFalse(demo.due_for_reset(self.conn))
        self.assertIsNone(demo.maybe_reset(self.conn))
        self.assertIsNone(demo.demo_user(self.conn))

    def test_a_zero_interval_leaves_the_command_line_as_the_only_way(self):
        demo.reset(self.conn)
        original = config.DEMO_RESET_HOURS
        config.DEMO_RESET_HOURS = 0
        try:
            later = display.utcnow().replace(year=display.utcnow().year + 1)
            self.assertFalse(demo.due_for_reset(self.conn, now=later))
        finally:
            config.DEMO_RESET_HOURS = original

    def test_the_workers_idle_pass_is_what_notices(self):
        self.assertIsNotNone(worker.maybe_reset_demo(self.conn))
        self.assertIsNone(worker.maybe_reset_demo(self.conn))

    def test_a_broken_reset_does_not_stop_the_thing_that_scrapes(self):
        original = demo.maybe_reset
        demo.maybe_reset = lambda _conn: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            with self.assertLogs("jobmatch.worker", level="ERROR"):
                self.assertIsNone(worker.maybe_reset_demo(self.conn))
        finally:
            demo.maybe_reset = original


class DemoSessionTests(DemoTestCase):
    """What the shared account may and may not do once somebody is in it."""

    def setUp(self):
        super().setUp()
        demo.reset(self.conn)
        self.client = webapp.app.test_client()
        res = self.client.post("/demo")
        self.assertEqual(res.status_code, 302, "the demo sign-in did not log anybody in")

    def test_one_click_lands_on_a_populated_dashboard(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        stats = self.client.get("/api/stats").get_json()
        self.assertGreater(stats["matched"], 0)
        self.assertEqual(stats["applied"], len(demo.SEEDED_APPLICATIONS))
        self.assertEqual(stats["declined"], demo.DECLINED_COUNT)
        self.assertEqual(len(self.client.get("/api/applications").get_json()["applications"]),
                         len(demo.SEEDED_APPLICATIONS))

    def test_a_visitor_can_actually_use_it(self):
        """Not read-only: the sliders move and jobs can be triaged."""
        job_id = self.client.get("/api/jobs").get_json()["jobs"][0]["id"]
        res = self.client.post(f"/api/jobs/{job_id}/status", json={"status": "declined"})
        self.assertEqual(res.status_code, 200)
        res = self.client.put("/api/settings", json={"weight_skill": 0.9})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["rescored"])

    def test_it_cannot_delete_itself(self):
        res = self.client.post("/api/account/delete", json={"password": config.DEMO_PASSWORD})
        self.assertEqual(res.status_code, 403)
        self.assertIn("demo account", res.get_json()["error"])
        self.assertIsNotNone(demo.demo_user(self.conn))

    def test_it_cannot_be_turned_into_a_public_pdf_drop_box(self):
        from tests.test_auth import MINIMAL_PDF

        res = self.client.post(
            "/api/resume",
            data={"resume": (__import__("io").BytesIO(MINIMAL_PDF), "cv.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 403)
        self.assertFalse(config.resume_path(demo.demo_user(self.conn)["id"]).exists())

    def test_it_cannot_trigger_the_shared_crawl(self):
        """Falls out of `is_admin = 0` — no special case in the scan route."""
        res = self.client.post("/api/scan/start")
        self.assertEqual(res.status_code, 403)

    def test_a_normal_account_is_not_treated_as_the_demo(self):
        self.make_user("real@example.com")
        real = self.client_for("real@example.com")
        res = real.post("/api/account/delete", json={"password": "wrong-password"})
        # Rejected for the ordinary reason, not the demo one.
        self.assertEqual(res.status_code, 403)
        self.assertNotIn("demo account", res.get_json()["error"])


class LandingPageTests(DemoTestCase):
    """The front door. Its only moving parts are the demo CTA and the signup gate."""

    def test_it_offers_the_demo_when_there_is_one(self):
        body = webapp.app.test_client().get("/").get_data(as_text=True)
        self.assertIn("Open the live demo", body)
        # The credentials are published on purpose — they protect nothing.
        self.assertIn(config.DEMO_EMAIL, body)
        self.assertIn(config.DEMO_PASSWORD, body)

    def test_the_demo_button_is_a_post_not_a_link(self):
        """A GET that signs somebody in can be triggered from anywhere."""
        body = webapp.app.test_client().get("/").get_data(as_text=True)
        self.assertIn('method="post" action="/demo"', body)
        self.assertEqual(webapp.app.test_client().get("/demo").status_code, 405)

    def test_a_closed_instance_does_not_advertise_signup(self):
        original = config.ALLOW_SIGNUP
        config.ALLOW_SIGNUP = False
        try:
            body = webapp.app.test_client().get("/").get_data(as_text=True)
        finally:
            config.ALLOW_SIGNUP = original
        self.assertNotIn("/signup", body)

    def test_every_screenshot_it_points_at_is_actually_there(self):
        """A landing page with four broken images is worse than none."""
        body = webapp.app.test_client().get("/").get_data(as_text=True)
        names = set(re.findall(r"/static/(screens/[\w-]+\.png)", body))
        self.assertTrue(names, "the landing page shows no screenshots at all")
        static = Path(webapp.app.static_folder)
        for name in sorted(names):
            self.assertTrue(
                (static / name).exists(),
                f"{name} is referenced but missing — run tools/screenshots.py",
            )

    def test_both_colour_schemes_are_covered(self):
        """The app has a dark mode; a light-only landing page misrepresents it."""
        body = webapp.app.test_client().get("/").get_data(as_text=True)
        self.assertIn('media="(prefers-color-scheme: dark)"', body)


class DemoDisabledTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self._demo_mode = config.DEMO_MODE
        config.DEMO_MODE = False

    def tearDown(self):
        config.DEMO_MODE = self._demo_mode
        super().tearDown()

    def test_the_sign_in_route_refuses_when_there_is_no_demo(self):
        client = webapp.app.test_client()
        res = client.post("/demo")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login", res.headers["Location"])
        self.assertIsNone(demo.demo_user(self.conn))

    def test_a_real_account_with_the_demo_address_is_still_a_real_account(self):
        """`in_demo` is gated on DEMO_MODE, not on the email alone."""
        self.make_user(config.DEMO_EMAIL, password=PASSWORD)
        client = self.client_for(config.DEMO_EMAIL, PASSWORD)
        res = client.post("/api/account/delete", json={"password": PASSWORD})
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()

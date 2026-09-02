"""Tests for Phase 8's email digest: what goes in one, and what never goes twice.

Two rules carry this feature, and both are here as assertions rather than as
comments in `jobmatch/digest.py`:

- **A job is emailed at most once.** `user_jobs.digested_at` is the record of
  what left the building, so re-scoring, a weight change or a second worker
  pass cannot resend it — while a job that only *becomes* a match later still
  arrives, which is the whole reason the mark is stored per row instead of
  being derived from a timestamp.
- **A broken mail server costs latency, not matches.** A failed send marks
  nothing and does not retry on the next ten-second poll.

No socket is opened: `jobmatch.mail.send` is replaced by a recorder, which is
also the only honest way to assert on what a message actually said.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import unittest
from datetime import timedelta

import config
from jobmatch import db, digest, display, mail, scoring, worker
from tests.test_auth import AuthTestCase

BASE_URL = "https://jobmatch.test"


class Recorder:
    """Stands in for `mail.send`. Records, or raises if told to."""

    def __init__(self, error=None):
        self.sent = []
        self.error = error

    def __call__(self, to, subject, text, html=None, headers=None):
        if self.error is not None:
            raise self.error
        self.sent.append({"to": to, "subject": subject, "text": text,
                          "html": html or "", "headers": headers or {}})
        return to

    @property
    def last(self):
        return self.sent[-1]


class DigestTestCase(AuthTestCase):
    """A configured mail server that goes nowhere, and a user with real matches."""

    def setUp(self):
        super().setUp()
        self._config = {
            key: getattr(config, key) for key in (
                "SMTP_HOST", "MAIL_FROM", "PUBLIC_BASE_URL",
                "DIGEST_INTERVAL_HOURS", "DIGEST_MAX_JOBS",
            )
        }
        config.SMTP_HOST = "smtp.test"
        config.MAIL_FROM = "jobmatch@test"
        config.PUBLIC_BASE_URL = BASE_URL
        config.DIGEST_INTERVAL_HOURS = 24
        config.DIGEST_MAX_JOBS = 10

        self._send = mail.send
        self.mailbox = Recorder()
        mail.send = self.mailbox

    def tearDown(self):
        mail.send = self._send
        for key, value in self._config.items():
            setattr(config, key, value)
        super().tearDown()

    def user_with_matches(self, email="her@example.com", count=3, threshold=50):
        """An account, some jobs it matches, and the scores to prove it."""
        user_id = self.make_user(email)
        for i in range(count):
            self.add_job(f"Python developer {i}", company=f"Company {i}")
        db.set_settings(self.conn, user_id, {
            "user_skills": ["python", "react"],
            "user_worktype": "remote",
            "min_match_score": threshold,
        })
        scoring.rescore_user(self.conn, user_id)
        return user_id

    def backdate_run(self, user_id, hours):
        """Move this user's last digest into the past."""
        when = display.utcnow() - timedelta(hours=hours)
        db.set_setting(self.conn, user_id, digest.RUN_KEY, when.isoformat(" ", "seconds"))

    def digested(self, user_id):
        return self.conn.scalar(
            "SELECT COUNT(*) FROM user_jobs WHERE user_id = :u AND digested_at IS NOT NULL",
            {"u": user_id},
        )


# ── What goes in one ─────────────────────────────────────────

class ContentTests(DigestTestCase):
    def test_a_digest_lists_the_matches_and_marks_them(self):
        user_id = self.user_with_matches()
        sent = digest.send_due(self.conn)

        self.assertEqual(len(sent), 1)
        self.assertEqual(len(self.mailbox.sent), 1)
        self.assertEqual(self.mailbox.last["to"], "her@example.com")
        self.assertEqual(sent[0]["sent"], 3)
        self.assertEqual(self.digested(user_id), 3)
        for i in range(3):
            self.assertIn(f"Python developer {i}", self.mailbox.last["text"])

    def test_the_subject_says_how_many_and_how_good(self):
        self.user_with_matches(count=4)
        digest.send_due(self.conn)
        subject = self.mailbox.last["subject"]
        self.assertIn("4 new job matches", subject)
        # The best score, as the email itself rounds it.
        self.assertRegex(subject, r"\(top \d+%\)")

    def test_one_match_is_not_pluralised(self):
        self.user_with_matches(count=1)
        digest.send_due(self.conn)
        self.assertIn("1 new job match (", self.mailbox.last["subject"])

    def test_only_what_the_dashboard_calls_a_match_goes_in(self):
        """`status = 'new'` and above the threshold — the same derivation, not a second one."""
        user_id = self.user_with_matches(count=3)
        job_ids = [
            row["job_id"] for row in self.conn.execute(
                "SELECT job_id FROM user_jobs WHERE user_id = :u ORDER BY job_id", {"u": user_id}
            )
        ]
        # One already applied to, one declined, one scored below the threshold.
        self.conn.execute(
            "UPDATE user_jobs SET status = 'applied' WHERE user_id = :u AND job_id = :j",
            {"u": user_id, "j": job_ids[0]},
        )
        self.conn.execute(
            "UPDATE user_jobs SET status = 'declined' WHERE user_id = :u AND job_id = :j",
            {"u": user_id, "j": job_ids[1]},
        )
        self.conn.execute(
            "UPDATE user_jobs SET match_score = 10 WHERE user_id = :u AND job_id = :j",
            {"u": user_id, "j": job_ids[2]},
        )
        self.conn.commit()

        self.assertEqual(digest.send_due(self.conn), [])
        self.assertEqual(self.mailbox.sent, [])
        # Nothing was sent, so nothing may be marked as sent either.
        self.assertEqual(self.digested(user_id), 0)

    def test_an_unscored_job_is_never_emailed(self):
        """A job with no description is deliberately unscored — not a 0% match."""
        user_id = self.user_with_matches(count=1)
        self.add_job("Mystery role", description="")
        scoring.rescore_user(self.conn, user_id)
        digest.send_due(self.conn)
        self.assertNotIn("Mystery role", self.mailbox.last["text"])

    def test_jobs_link_into_the_app_when_it_has_an_address(self):
        user_id = self.user_with_matches(count=1)
        job_id = self.conn.scalar(
            "SELECT job_id FROM user_jobs WHERE user_id = :u", {"u": user_id}
        )
        digest.send_due(self.conn)
        self.assertIn(f"{BASE_URL}/jobs/{job_id}", self.mailbox.last["text"])
        self.assertIn(f"{BASE_URL}/jobs/{job_id}", self.mailbox.last["html"])

    def test_without_a_public_address_it_links_to_the_board(self):
        """`http://None/jobs/12` is worse than the posting itself."""
        config.PUBLIC_BASE_URL = ""
        self.user_with_matches(count=1)
        digest.send_due(self.conn)
        self.assertIn("http://x/Python developer 0", self.mailbox.last["text"])
        self.assertNotIn("None/jobs", self.mailbox.last["text"])
        # And with nowhere to unsubscribe, the header is left off rather than
        # pointed at a URL that does not resolve.
        self.assertNotIn("List-Unsubscribe", self.mailbox.last["headers"])

    def test_the_unsubscribe_header_points_at_settings(self):
        self.user_with_matches(count=1)
        digest.send_due(self.conn)
        self.assertEqual(
            self.mailbox.last["headers"]["List-Unsubscribe"], f"<{BASE_URL}/settings>"
        )

    def test_the_html_part_escapes_what_a_board_wrote(self):
        """Job titles are scraped, so they are somebody else's markup until escaped."""
        self.user_with_matches(count=0)
        self.add_job("<script>alert(1)</script> developer")
        user_id = db.get_user_by_email(self.conn, "her@example.com")["id"]
        scoring.rescore_user(self.conn, user_id)
        digest.send_due(self.conn)
        self.assertNotIn("<script>", self.mailbox.last["html"])
        self.assertIn("&lt;script&gt;", self.mailbox.last["html"])

    def test_a_full_digest_says_how_many_are_waiting_and_keeps_them(self):
        config.DIGEST_MAX_JOBS = 2
        user_id = self.user_with_matches(count=5)

        first = digest.send_due(self.conn)[0]
        self.assertEqual(first["sent"], 2)
        self.assertEqual(first["waiting"], 5)
        self.assertIn("and 3 more", self.mailbox.last["text"])
        # The three that did not fit are not marked, so they are not lost.
        self.assertEqual(self.digested(user_id), 2)

        self.backdate_run(user_id, hours=25)
        second = digest.send_due(self.conn)[0]
        self.assertEqual(second["sent"], 2)
        self.assertEqual(second["waiting"], 3)
        self.assertEqual(self.digested(user_id), 4)


# ── Nothing goes twice ───────────────────────────────────────

class NoRepeatTests(DigestTestCase):
    def test_a_second_pass_sends_nothing(self):
        self.user_with_matches()
        digest.send_due(self.conn)
        digest.send_due(self.conn)
        self.assertEqual(len(self.mailbox.sent), 1)

    def test_even_forced_the_same_jobs_do_not_come_back(self):
        """The schedule is the polite guard; `digested_at` is the real one."""
        user_id = self.user_with_matches()
        digest.send_due(self.conn)
        self.backdate_run(user_id, hours=99)
        self.assertEqual(digest.send_due(self.conn, force=True), [])
        self.assertEqual(len(self.mailbox.sent), 1)

    def test_rescoring_does_not_resend(self):
        user_id = self.user_with_matches()
        digest.send_due(self.conn)
        scoring.rescore_user(self.conn, user_id)
        self.backdate_run(user_id, hours=25)
        digest.send_due(self.conn)
        self.assertEqual(len(self.mailbox.sent), 1)

    def test_a_job_that_becomes_a_match_later_is_still_news(self):
        """Why the mark is per row: a weight change makes real news out of an old job."""
        user_id = self.user_with_matches(count=1, threshold=50)
        self.add_job("Java developer", skills="java", description="Java on site.",
                     worktype="onsite")
        scoring.rescore_user(self.conn, user_id)
        digest.send_due(self.conn)
        self.assertNotIn("Java developer", self.mailbox.last["text"])

        # They drop their threshold; the job they were never told about qualifies.
        db.set_setting(self.conn, user_id, "min_match_score", 0)
        self.backdate_run(user_id, hours=25)
        digest.send_due(self.conn)
        self.assertEqual(len(self.mailbox.sent), 2)
        self.assertIn("Java developer", self.mailbox.last["text"])

    def test_marking_one_user_leaves_the_other_alone(self):
        """The pool is shared; what was emailed to whom is not."""
        first = self.user_with_matches("first@example.com")
        second = self.make_user("second@example.com")
        db.set_settings(self.conn, second, {
            "user_skills": ["python", "react"], "user_worktype": "remote",
            "min_match_score": 50,
        })
        scoring.rescore_user(self.conn, second)

        digest.send_for_user(self.conn, first, "first@example.com")
        self.assertEqual(self.digested(first), 3)
        self.assertEqual(self.digested(second), 0)


# ── The schedule ─────────────────────────────────────────────

class ScheduleTests(DigestTestCase):
    def test_a_new_account_is_due_at_once(self):
        user_id = self.user_with_matches()
        self.assertTrue(digest.due(self.conn, user_id))

    def test_the_interval_is_a_question_about_the_last_run(self):
        user_id = self.user_with_matches()
        digest.send_due(self.conn)
        self.assertFalse(digest.due(self.conn, user_id))
        self.backdate_run(user_id, hours=23)
        self.assertFalse(digest.due(self.conn, user_id))
        self.backdate_run(user_id, hours=25)
        self.assertTrue(digest.due(self.conn, user_id))

    def test_an_empty_digest_is_not_sent_but_still_counts_as_a_run(self):
        """Otherwise a user with nothing new is re-queried on every ten-second poll."""
        user_id = self.make_user("quiet@example.com")
        self.assertEqual(digest.send_due(self.conn), [])
        self.assertEqual(self.mailbox.sent, [])
        self.assertFalse(digest.due(self.conn, user_id))

    def test_a_user_who_turned_it_off_gets_nothing(self):
        user_id = self.user_with_matches()
        db.set_setting(self.conn, user_id, "digest_enabled", False)
        self.assertFalse(digest.due(self.conn, user_id))
        self.assertEqual(digest.send_due(self.conn), [])
        self.assertEqual(self.digested(user_id), 0)

    def test_an_instance_with_no_mail_server_sends_nothing(self):
        config.SMTP_HOST = ""
        user_id = self.user_with_matches()
        self.assertFalse(digest.enabled())
        self.assertEqual(digest.maybe_send(self.conn), [])
        self.assertEqual(self.mailbox.sent, [])
        self.assertEqual(self.digested(user_id), 0)

    def test_interval_zero_turns_the_schedule_off_but_not_the_command(self):
        config.DIGEST_INTERVAL_HOURS = 0
        self.user_with_matches()
        self.assertEqual(digest.maybe_send(self.conn), [])
        self.assertEqual(self.mailbox.sent, [])
        # …which is what `python3 -m jobmatch.digest --force` is for.
        self.assertEqual(len(digest.send_due(self.conn, force=True)), 1)

    def test_the_demo_account_is_never_emailed(self):
        """Its address is published, is nobody's inbox, and resets every night."""
        self.user_with_matches(email=config.DEMO_EMAIL)
        self.assertEqual(digest.candidates(self.conn), [])
        self.assertEqual(digest.send_due(self.conn), [])
        self.assertEqual(self.mailbox.sent, [])


# ── When the mail server is down ─────────────────────────────

class FailureTests(DigestTestCase):
    def test_a_failed_send_marks_nothing_and_does_not_retry_immediately(self):
        user_id = self.user_with_matches()
        mail.send = Recorder(error=OSError("connection refused"))

        self.assertEqual(digest.send_due(self.conn), [])
        self.assertEqual(self.digested(user_id), 0)
        # The run is stamped anyway, so a relay that is down is not hammered
        # once per poll for as long as it stays down.
        self.assertFalse(digest.due(self.conn, user_id))

        # Nothing was lost: the next cycle carries the same jobs.
        mail.send = self.mailbox
        self.backdate_run(user_id, hours=25)
        self.assertEqual(digest.send_due(self.conn)[0]["sent"], 3)

    def test_one_users_failure_does_not_stop_the_next(self):
        class Selective(Recorder):
            def __call__(self, to, subject, text, html=None, headers=None):
                if to == "first@example.com":
                    raise OSError("mailbox full")
                return super().__call__(to, subject, text, html=html, headers=headers)

        self.user_with_matches("first@example.com")
        second = self.user_with_matches("second@example.com", count=0)
        mail.send = Selective()

        sent = digest.send_due(self.conn)
        self.assertEqual([s["email"] for s in sent], ["second@example.com"])
        self.assertEqual(self.digested(second), 3)


# ── The transport ────────────────────────────────────────────

class MailTests(unittest.TestCase):
    """`mail.build` only — nothing here opens a socket."""

    def setUp(self):
        self._config = (config.SMTP_HOST, config.MAIL_FROM, config.MAIL_FROM_NAME)
        config.SMTP_HOST, config.MAIL_FROM, config.MAIL_FROM_NAME = (
            "smtp.test", "bot@test", "JobMatch"
        )

    def tearDown(self):
        config.SMTP_HOST, config.MAIL_FROM, config.MAIL_FROM_NAME = self._config

    def test_configured_needs_a_host_and_a_sender(self):
        self.assertTrue(mail.configured())
        config.MAIL_FROM = ""
        self.assertFalse(mail.configured())
        config.MAIL_FROM, config.SMTP_HOST = "bot@test", ""
        self.assertFalse(mail.configured())

    def test_the_plain_part_comes_first(self):
        """Clients render the last part they understand, so text must lead."""
        message = mail.build("her@example.com", "Subject", "plain", html="<p>rich</p>")
        parts = [part.get_content_type() for part in message.walk()]
        self.assertEqual(parts[0], "multipart/alternative")
        self.assertEqual(parts[1:], ["text/plain", "text/html"])

    def test_text_only_is_not_a_multipart(self):
        message = mail.build("her@example.com", "Subject", "plain")
        self.assertEqual(message.get_content_type(), "text/plain")

    def test_the_sender_carries_a_name_and_extra_headers_survive(self):
        message = mail.build("her@example.com", "Subject", "plain",
                             headers={"List-Unsubscribe": "<https://x/settings>"})
        self.assertEqual(message["From"], "JobMatch <bot@test>")
        self.assertEqual(message["To"], "her@example.com")
        self.assertEqual(message["List-Unsubscribe"], "<https://x/settings>")

    def test_sending_without_a_server_is_an_error_not_a_silent_no_op(self):
        config.SMTP_HOST = ""
        with self.assertRaises(RuntimeError):
            mail.send("her@example.com", "Subject", "plain")


# ── The worker and the web tier ──────────────────────────────

class WorkerTests(DigestTestCase):
    def test_an_idle_pass_sends_the_digests(self):
        config.SCAN_ENABLED = False
        user_id = self.user_with_matches()
        worker.run(once=True)
        self.assertEqual(len(self.mailbox.sent), 1)
        self.assertEqual(self.digested(user_id), 3)

    def test_a_broken_digest_does_not_stop_the_loop(self):
        """A mail server having a bad night must not stop the thing that scrapes."""
        original = digest.maybe_send
        digest.maybe_send = lambda conn: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            self.assertEqual(worker.maybe_send_digests(self.conn), [])
        finally:
            digest.maybe_send = original


class SettingsRouteTests(DigestTestCase):
    def test_settings_report_the_preference_and_the_deployment_separately(self):
        self.make_user("her@example.com")
        client = self.client_for("her@example.com")
        settings = client.get("/api/settings").get_json()
        self.assertTrue(settings["digest_enabled"])
        self.assertTrue(settings["digest_available"])
        self.assertEqual(settings["digest_interval_hours"], 24)

        config.SMTP_HOST = ""
        self.assertFalse(client.get("/api/settings").get_json()["digest_available"])

    def test_a_user_can_turn_their_own_digest_off(self):
        user_id = self.make_user("her@example.com")
        client = self.client_for("her@example.com")
        res = client.put("/api/settings", json={"digest_enabled": False})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(db.get_setting(self.conn, user_id, "digest_enabled"))

    def test_nobody_can_put_themselves_a_fresh_digest(self):
        """`digest_run_at` is not a setting — it is the schedule's own bookkeeping."""
        user_id = self.user_with_matches()
        digest.send_due(self.conn)
        stamp = db.get_setting(self.conn, user_id, digest.RUN_KEY)

        client = self.client_for("her@example.com")
        client.put("/api/settings", json={digest.RUN_KEY: "2000-01-01 00:00:00"})
        self.assertEqual(db.get_setting(self.conn, user_id, digest.RUN_KEY), stamp)


if __name__ == "__main__":
    unittest.main()

"""Tests for Phase 4: `scans` as the queue, and the worker that drains it.

The load-bearing check is the Phase 4 verification checkpoint from ROADMAP.md —
"kill the worker mid-scan, restart, confirm the orphaned row is reconciled and
no scan is lost or duplicated". `OrphanTests` and `WorkerLoopTests` are that
checkpoint written down: a killed worker is a `running` row whose heartbeat
stopped, and a restart is `worker.run()` booting against it.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

import config
from jobmatch import db, display, places, scan, worker  # noqa: E402
from jobmatch.sources.base import JobSource  # noqa: E402

# Importing the auth suite for its harness also switches rate limiting off
# before `app` is imported, which is the only order in which that works.
from tests.test_auth import AuthTestCase  # noqa: E402,I001


class FakeSource(JobSource):
    """A board that answers instantly, from memory, with no politeness delay."""

    name = "fake"
    label = "Fake board"
    needs_browser = False

    def __init__(self, count=2, on_search=None, listed=None):
        self.count = count
        self.on_search = on_search
        self.searches = 0
        # What the board *showed* us, as opposed to what was new about it —
        # the two are the same on a first scan and diverge on every later one.
        self.listed = count if listed is None else listed

    def search(self, page, terms, days, known_ids, ctx):
        self.searches += 1
        if self.on_search:
            self.on_search(ctx)
        ctx.seen(self.listed)
        return [
            {
                "source_id": f"fake-{i}", "title": f"Python developer {i}",
                "company": "ACME", "location": "Bratislava", "salary": "",
                "freshness": "", "link": f"https://example.test/{i}",
                # A description means the enrich phase has nothing to fetch,
                # which is what keeps these tests free of network and sleeps.
                "description": "Python, React, práca z domu.",
            }
            for i in range(self.count)
            if f"fake-{i}" not in known_ids
        ]


class QueueTestCase(unittest.TestCase):
    """A throwaway database with one admin. No Flask, no network."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = (config.DB_PATH, config.SCAN_ENABLED, config.SCAN_INTERVAL_HOURS)
        config.DB_PATH = Path(self._tmp.name) / "test.db"
        config.SCAN_ENABLED = True
        self.conn = db.get_conn()
        db.init_schema(self.conn)
        self.admin = db.create_user(self.conn, "admin@example.test", "x", is_admin=True)
        self.conn.commit()
        # No board by default. The shipped default enables all six, so a test
        # that runs a scan without saying otherwise would go and scrape the
        # actual internet — slowly, and from whoever's machine runs the suite.
        db.set_settings(self.conn, self.admin, {"enabled_sources": []})
        worker._shutdown.clear()

    def tearDown(self):
        self.conn.close()
        config.DB_PATH, config.SCAN_ENABLED, config.SCAN_INTERVAL_HOURS = self._orig
        worker._shutdown.clear()
        self._tmp.cleanup()

    def stamp(self, **delta):
        """A stored-shape timestamp, offset from now."""
        return (display.utcnow() - timedelta(**delta)).isoformat(sep=" ", timespec="seconds")

    def scan_row(self, scan_id):
        return self.conn.execute(
            "SELECT * FROM scans WHERE id = :id", {"id": scan_id}
        ).fetchone()


# ── Queueing ─────────────────────────────────────────────────

class EnqueueTests(QueueTestCase):
    def test_a_trigger_only_queues(self):
        state, error = scan.enqueue(self.conn, self.admin, "manual")
        self.assertIsNone(error)
        self.assertEqual(state["status"], "queued")
        row = self.scan_row(state["scan_id"])
        self.assertEqual(row["trigger"], "manual")
        self.assertEqual(row["requested_by"], self.admin)
        self.assertIsNone(row["claimed_by"], "nothing has claimed it yet")

    def test_only_one_scan_can_be_active(self):
        first, _ = scan.enqueue(self.conn, self.admin)
        state, error = scan.enqueue(self.conn, self.admin)
        self.assertIsNone(state)
        self.assertIn("already", error)
        # Same again once it is running rather than queued.
        scan.claim_next(self.conn, "worker-1")
        self.assertIsNotNone(scan.enqueue(self.conn, self.admin)[1])
        self.assertEqual(
            self.conn.scalar("SELECT COUNT(*) FROM scans"), 1, "no duplicate row"
        )
        self.assertEqual(first["status"], "queued")

    def test_the_queue_reopens_once_a_scan_finishes(self):
        scan.enqueue(self.conn, self.admin)
        claimed = scan.claim_next(self.conn, "worker-1")
        scan.run_claimed(self.conn, claimed)
        state, error = scan.enqueue(self.conn, self.admin)
        self.assertIsNone(error)
        self.assertEqual(state["status"], "queued")


class ClaimTests(QueueTestCase):
    def test_claiming_marks_the_row_running(self):
        state, _ = scan.enqueue(self.conn, self.admin)
        claimed = scan.claim_next(self.conn, "worker-1")
        self.assertEqual(claimed["id"], state["scan_id"])
        row = self.scan_row(claimed["id"])
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["claimed_by"], "worker-1")
        self.assertIsNotNone(row["heartbeat_at"])

    def test_a_second_worker_claims_nothing(self):
        scan.enqueue(self.conn, self.admin)
        self.assertIsNotNone(scan.claim_next(self.conn, "worker-1"))
        self.assertIsNone(
            scan.claim_next(self.conn, "worker-2"),
            "two workers must never run the same scan",
        )

    def test_an_empty_queue_claims_nothing(self):
        self.assertIsNone(scan.claim_next(self.conn, "worker-1"))

    def test_the_oldest_queued_scan_goes_first(self):
        first, _ = scan.enqueue(self.conn, self.admin)
        # Force a second queued row past the one-active guard, as a race would.
        second = self.conn.scalar(
            "INSERT INTO scans (status, \"trigger\") VALUES ('queued', 'manual') RETURNING id"
        )
        self.conn.commit()
        self.assertEqual(scan.claim_next(self.conn, "worker-1")["id"], first["scan_id"])
        self.assertNotEqual(second, first["scan_id"])


# ── Status, read by a process that is not scanning ───────────

class StatusTests(QueueTestCase):
    def test_status_comes_from_the_row_not_from_this_process(self):
        state, _ = scan.enqueue(self.conn, self.admin)
        claimed = scan.claim_next(self.conn, "worker-1")
        running = scan.ScanState(self.conn, claimed)
        running.found = 7
        running.set_phase("Searching Fake board")

        # A second connection stands in for the web worker that knows nothing
        # about the scan — the whole reason the state left module globals.
        with db.get_conn() as other:
            status = scan.current_status(other)
        self.assertEqual(status["scan_id"], state["scan_id"])
        self.assertEqual(status["status"], "running")
        self.assertEqual(status["phase"], "Searching Fake board")
        self.assertEqual(status["found"], 7)

    def test_status_of_a_database_that_never_scanned_is_none(self):
        self.assertIsNone(scan.current_status(self.conn))

    def test_status_does_not_leak_the_traceback(self):
        scan.enqueue(self.conn, self.admin)
        claimed = scan.claim_next(self.conn, "worker-1")
        state = scan.ScanState(self.conn, claimed)
        state.status, state.error = "failed", "Traceback (most recent call last): …"
        scan._finalize(state, self.conn)
        status = scan.current_status(self.conn)
        self.assertEqual(status["status"], "failed")
        self.assertNotIn("error", status)
        self.assertIn("Traceback", self.scan_row(claimed["id"])["error"], "kept for the log")


# ── Cancellation across processes ────────────────────────────

class CancelTests(QueueTestCase):
    def test_a_running_scan_sees_the_flag_another_process_set(self):
        scan.enqueue(self.conn, self.admin)
        claimed = scan.claim_next(self.conn, "worker-1")
        state = scan.ScanState(self.conn, claimed)
        self.assertFalse(state.stopped())

        with db.get_conn() as other:      # the web process, elsewhere
            self.assertTrue(scan.request_stop(other))

        state.sync(force=True)            # the next heartbeat, without the wait
        self.assertTrue(state.stopped())

    def test_a_queued_scan_is_cancelled_outright(self):
        state, _ = scan.enqueue(self.conn, self.admin)
        self.assertTrue(scan.request_stop(self.conn))
        row = self.scan_row(state["scan_id"])
        self.assertEqual(row["status"], "cancelled", "nobody would ever pick it up")
        self.assertIsNotNone(row["finished_at"])
        self.assertIsNone(scan.claim_next(self.conn, "worker-1"))

    def test_cancelling_with_nothing_active_says_so(self):
        self.assertFalse(scan.request_stop(self.conn))


# ── Orphans: the Phase 4 checkpoint ──────────────────────────

class OrphanTests(QueueTestCase):
    def running_row(self, heartbeat, started=None):
        scan_id = self.conn.scalar(
            """INSERT INTO scans (status, started_at, heartbeat_at, "trigger")
               VALUES ('running', :started, :heartbeat, 'manual') RETURNING id""",
            {"started": started or self.stamp(minutes=10), "heartbeat": heartbeat},
        )
        self.conn.commit()
        return scan_id

    def test_a_live_heartbeat_is_left_alone(self):
        scan_id = self.running_row(self.stamp(seconds=1))
        self.assertEqual(scan.reconcile_orphans(self.conn), 0)
        self.assertEqual(self.scan_row(scan_id)["status"], "running")

    def test_a_dead_worker_is_reconciled_and_unblocks_the_queue(self):
        scan_id = self.running_row(self.stamp(minutes=30))
        self.assertIsNotNone(scan.enqueue(self.conn, self.admin)[1], "blocked while running")

        self.assertEqual(scan.reconcile_orphans(self.conn), 1)
        row = self.scan_row(scan_id)
        self.assertEqual(row["status"], "failed")
        self.assertIsNotNone(row["finished_at"])
        self.assertIn("stopped", row["error"])
        self.assertIsNone(scan.enqueue(self.conn, self.admin)[1], "queue is free again")

    def test_a_row_from_before_the_heartbeat_column_falls_back_to_started_at(self):
        scan_id = self.running_row(None, started=self.stamp(days=2))
        self.assertEqual(scan.reconcile_orphans(self.conn), 1)
        self.assertEqual(self.scan_row(scan_id)["status"], "failed")

    def test_reconciling_twice_changes_nothing(self):
        self.running_row(self.stamp(minutes=30))
        self.assertEqual(scan.reconcile_orphans(self.conn), 1)
        self.assertEqual(scan.reconcile_orphans(self.conn), 0)


# ── The worker loop ──────────────────────────────────────────

class WorkerLoopTests(QueueTestCase):
    def setUp(self):
        super().setUp()
        self._sources = (scan.SOURCES, scan.get_enabled)
        db.set_settings(self.conn, self.admin, {"enabled_sources": ["fake"]})
        self.source = FakeSource()
        scan.SOURCES = {"fake": self.source}
        scan.get_enabled = lambda names: [self.source]

    def tearDown(self):
        scan.SOURCES, scan.get_enabled = self._sources
        super().tearDown()

    def test_the_worker_runs_a_queued_scan_end_to_end(self):
        state, _ = scan.enqueue(self.conn, self.admin, "manual")
        worker.run(once=True)

        row = self.scan_row(state["scan_id"])
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["found"], 2)
        self.assertEqual(row["phase"], "Finished")
        self.assertIsNotNone(row["finished_at"])
        self.assertEqual(self.conn.scalar("SELECT COUNT(*) FROM jobs"), 2)
        # A finished scan scores the pool for every user, not just the trigger's.
        self.assertEqual(
            self.conn.scalar(
                "SELECT COUNT(*) FROM user_jobs WHERE user_id = :u AND match_score IS NOT NULL",
                {"u": self.admin},
            ), 2,
        )

    def test_a_second_pass_finds_nothing_new_and_does_not_rerun(self):
        scan.enqueue(self.conn, self.admin)
        worker.run(once=True)
        config.SCAN_INTERVAL_HOURS = 6      # the scan just now satisfies it
        worker.run(once=True)
        self.assertEqual(self.source.searches, 1, "no scan may run twice")
        self.assertEqual(self.conn.scalar("SELECT COUNT(*) FROM scans"), 1)

    def test_shutdown_mid_scan_cancels_rather_than_orphaning(self):
        # The signal lands while the board is being searched — a `docker
        # compose stop`, or the Ctrl-C in the checkpoint.
        self.source.on_search = lambda ctx: worker._shutdown.set()
        state, _ = scan.enqueue(self.conn, self.admin)
        worker.run(once=True)

        row = self.scan_row(state["scan_id"])
        self.assertEqual(row["status"], "cancelled")
        self.assertIsNotNone(row["finished_at"], "not left running for a restart to find")
        self.assertEqual(
            self.conn.scalar("SELECT COUNT(*) FROM jobs"), 2,
            "jobs found before the stop are committed, not rolled back",
        )

    def test_a_restart_reconciles_what_a_kill_left_behind(self):
        # -9 leaves exactly this: `running`, claimed, heartbeat stopped.
        scan_id = self.conn.scalar(
            """INSERT INTO scans (status, started_at, heartbeat_at, claimed_by, "trigger")
               VALUES ('running', :then, :then, 'dead-worker:1', 'manual') RETURNING id""",
            {"then": self.stamp(minutes=30)},
        )
        self.conn.commit()
        config.SCAN_INTERVAL_HOURS = 0      # keep the schedule out of this test

        worker.run(once=True)               # the restart

        self.assertEqual(self.scan_row(scan_id)["status"], "failed")
        self.assertEqual(self.source.searches, 0, "the dead scan is not re-run")
        self.assertIsNone(scan.enqueue(self.conn, self.admin)[1])


class ScheduleTests(QueueTestCase):
    def test_a_database_that_never_scanned_is_due(self):
        config.SCAN_INTERVAL_HOURS = 6
        self.assertTrue(worker.due_for_scan(self.conn))
        scan_id = worker.maybe_schedule(self.conn)
        row = self.scan_row(scan_id)
        self.assertEqual(row["trigger"], "schedule")
        self.assertEqual(row["requested_by"], self.admin, "attributed to the admin")

    def test_a_recent_scan_is_not_due(self):
        config.SCAN_INTERVAL_HOURS = 6
        self.conn.execute(
            "INSERT INTO scans (status, started_at) VALUES ('done', :then)",
            {"then": self.stamp(hours=1)},
        )
        self.conn.commit()
        self.assertFalse(worker.due_for_scan(self.conn))
        self.assertIsNone(worker.maybe_schedule(self.conn))

    def test_an_old_scan_is_due_again(self):
        config.SCAN_INTERVAL_HOURS = 6
        self.conn.execute(
            "INSERT INTO scans (status, started_at) VALUES ('done', :then)",
            {"then": self.stamp(hours=7)},
        )
        self.conn.commit()
        self.assertTrue(worker.due_for_scan(self.conn))

    def test_scheduling_can_be_switched_off(self):
        config.SCAN_INTERVAL_HOURS = 0
        self.assertFalse(worker.due_for_scan(self.conn))
        config.SCAN_INTERVAL_HOURS = 6
        config.SCAN_ENABLED = False
        self.assertFalse(worker.due_for_scan(self.conn))

    def test_an_instance_with_no_accounts_does_not_scrape(self):
        config.SCAN_INTERVAL_HOURS = 6
        db.delete_user(self.conn, self.admin)
        self.assertFalse(
            worker.due_for_scan(self.conn),
            "there are no search settings to scan with, and nobody to scan for",
        )


# ── The routes in front of the queue ─────────────────────────

class ScanRouteTests(AuthTestCase):
    """Triggering the shared crawl is an admin act; watching it is not."""

    def setUp(self):
        super().setUp()
        self._scan_enabled = config.SCAN_ENABLED
        config.SCAN_ENABLED = True
        self.admin = self.make_user("admin@example.test", is_admin=True)
        self.member = self.make_user("member@example.test")

    def tearDown(self):
        config.SCAN_ENABLED = self._scan_enabled
        super().tearDown()

    def test_an_admin_queues_a_scan(self):
        res = self.client_for("admin@example.test").post("/api/scan/start")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "queued")
        self.assertEqual(
            self.conn.scalar("SELECT requested_by FROM scans"), self.admin
        )

    def test_a_regular_user_may_not(self):
        res = self.client_for("member@example.test").post("/api/scan/start")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.conn.scalar("SELECT COUNT(*) FROM scans"), 0)

    def test_a_regular_user_may_not_cancel_either(self):
        scan.enqueue(self.conn, self.admin)
        res = self.client_for("member@example.test").post("/api/scan/cancel")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.conn.scalar("SELECT status FROM scans"), "queued")

    def test_everyone_can_watch(self):
        scan.enqueue(self.conn, self.admin)
        for email in ("admin@example.test", "member@example.test"):
            res = self.client_for(email).get("/api/scan/status")
            self.assertEqual(res.status_code, 200, email)
            self.assertEqual(res.get_json()["status"], "queued", email)

    def test_no_scan_at_all_reads_as_idle(self):
        res = self.client_for("member@example.test").get("/api/scan/status")
        self.assertEqual(res.get_json(), {"status": "idle"})

    def test_a_second_trigger_is_a_conflict(self):
        client = self.client_for("admin@example.test")
        self.assertEqual(client.post("/api/scan/start").status_code, 200)
        self.assertEqual(client.post("/api/scan/start").status_code, 409)

    def test_scanning_switched_off_refuses(self):
        config.SCAN_ENABLED = False
        res = self.client_for("admin@example.test").post("/api/scan/start")
        self.assertEqual(res.status_code, 503)

    def test_the_scan_button_is_only_rendered_for_an_admin(self):
        admin_page = self.client_for("admin@example.test").get("/").get_data(as_text=True)
        member_page = self.client_for("member@example.test").get("/").get_data(as_text=True)
        # The id, not the name: the click handler mentions it either way.
        self.assertIn('id="btn-scan"', admin_page)
        self.assertNotIn('id="btn-scan"', member_page)
        self.assertIn("window.CAN_SCAN = false", member_page)


# ── Telling a quiet board from a quiet day ───────────────────

class SourceYieldTests(QueueTestCase):
    """Phase 8: a board that returns nothing at all has to say so.

    Zero new jobs is the ordinary outcome of an incremental scan. Zero
    *listings* means the board is down, blocking us, or redesigned — a failure
    that raises nothing and finishes green, which is why it needs a test of its
    own rather than an exception handler.
    """

    def _state(self):
        scan.enqueue(self.conn, self.admin)
        return scan.ScanState(
            self.conn, scan.claim_next(self.conn, "worker-1"),
            should_stop=worker._shutdown.is_set,   # wired exactly as the worker wires it
        )

    def test_a_board_that_lists_nothing_is_reported(self):
        state = self._state()
        source = FakeSource(count=0, listed=0)

        scan._search_phase(state, self.conn, None, [source], ["python"], 7)

        self.assertIn("fake", state.source_errors)
        self.assertIn("no listings", state.source_errors["fake"])

    def test_a_board_with_nothing_new_is_not_reported(self):
        """The false positive this whole mechanism exists to avoid."""
        state = self._state()
        source = FakeSource(count=2)
        # Everything it has, we already stored — so it yields no stubs at all.
        scan._search_phase(state, self.conn, None, [source], ["python"], 7)
        state.source_errors.clear()
        scan._search_phase(state, self.conn, None, [source], ["python"], 7)

        self.assertEqual(state.source_errors, {}, "a quiet day is not a broken board")
        self.assertEqual(state.source_seen["fake"], 4, "it answered both times")

    def test_an_adapter_that_reports_nothing_but_returns_stubs_is_trusted(self):
        state = self._state()
        source = FakeSource(count=2, listed=0)   # stubs without a seen() report

        scan._search_phase(state, self.conn, None, [source], ["python"], 7)

        self.assertEqual(state.source_errors, {}, "stubs are their own proof of life")
        self.assertEqual(state.found, 2)

    def test_a_search_that_raises_keeps_its_own_message(self):
        state = self._state()
        source = FakeSource(count=0, listed=0)
        source.on_search = lambda ctx: (_ for _ in ()).throw(RuntimeError("403 Forbidden"))

        scan._search_phase(state, self.conn, None, [source], ["python"], 7)

        self.assertIn("403 Forbidden", state.source_errors["fake"])

    def test_a_cancelled_scan_does_not_accuse_the_board(self):
        state = self._state()
        source = FakeSource(count=0, listed=0)
        # A SIGTERM lands while the board is being searched, so the adapter
        # comes back empty because we cut it short — not because it is broken.
        source.on_search = lambda ctx: (worker._shutdown.set(), ctx.stopped())

        scan._search_phase(state, self.conn, None, [source], ["python"], 7)

        self.assertEqual(state.source_errors, {}, "we stopped it; it did not fail")

    def test_the_alert_reaches_the_scan_row_and_the_poller(self):
        state = self._state()
        scan._search_phase(state, self.conn, None, [FakeSource(count=0, listed=0)],
                           ["python"], 7)
        state.status = "done"
        scan._finalize(state, self.conn)

        status = scan.current_status(self.conn)
        self.assertIn("fake", status["source_errors"])
        self.assertEqual(
            self.conn.scalar("SELECT status FROM scans WHERE id = :id", {"id": state.scan_id}),
            "done", "a silent board is a warning about the board, not a failed scan",
        )


class EnrichFailureTests(QueueTestCase):
    """A detail page that stops parsing must show up as a failed read."""

    class SilentDetailSource(FakeSource):
        name = "silent"
        label = "Silent board"

        def fetch_detail(self, page, url):
            return ""       # the shape a moved selector arrives in

    class FeedSource(FakeSource):
        name = "feed"
        label = "Feed board"
        has_detail_page = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.detail_calls = 0

        def fetch_detail(self, page, url):
            self.detail_calls += 1
            return ""

    def setUp(self):
        super().setUp()
        self._sources = scan.SOURCES
        self._delays = (config.MIN_DETAIL_DELAY, config.MAX_DETAIL_DELAY)
        config.MIN_DETAIL_DELAY = config.MAX_DETAIL_DELAY = 0.0

    def tearDown(self):
        scan.SOURCES = self._sources
        config.MIN_DETAIL_DELAY, config.MAX_DETAIL_DELAY = self._delays
        super().tearDown()

    def _pending_job(self, source_name):
        self.conn.execute(
            """INSERT INTO jobs (source, source_id, title, link, description)
               VALUES (:source, '1', 'python developer', 'https://example.test/1', '')""",
            {"source": source_name},
        )
        self.conn.commit()
        scan.enqueue(self.conn, self.admin)
        return scan.ScanState(self.conn, scan.claim_next(self.conn, "worker-1"))

    def test_a_description_that_never_arrives_counts_as_failed(self):
        source = self.SilentDetailSource()
        scan.SOURCES = {"silent": source}
        state = self._pending_job("silent")

        scan._enrich_phase(state, self.conn, None)

        self.assertEqual(state.enriched, 0)
        self.assertEqual(state.failed, 1, "an empty read is a failed read, not a quiet success")

    def test_a_feed_board_is_never_asked_for_a_detail_page(self):
        source = self.FeedSource()
        scan.SOURCES = {"feed": source}
        state = self._pending_job("feed")

        scan._enrich_phase(state, self.conn, None)

        self.assertEqual(source.detail_calls, 0, "there is no detail page to fetch")
        self.assertEqual(state.failed, 0, "and therefore nothing failed")


class EnrichProvidesTests(QueueTestCase):
    """A source's structured fields beat regex extraction — here too.

    Unreachable until `jobscz`, which is the first board with both a `provides`
    declaration and a detail page: every earlier one that stated a field was a
    feed board, so the enrich phase never ran over a column a board had filled
    in and could overwrite it unconditionally without anybody noticing.
    """

    class StatingSource(FakeSource):
        name = "stating"
        label = "Stating board"
        provides = frozenset({"worktype"})

        def fetch_detail(self, page, url):
            # Prose that says nothing about a work mode — which is exactly the
            # case that used to erase what the card had already stated.
            return "We are hiring a senior python developer. Django, React."

    def setUp(self):
        super().setUp()
        self._sources = scan.SOURCES
        self._delays = (config.MIN_DETAIL_DELAY, config.MAX_DETAIL_DELAY)
        config.MIN_DETAIL_DELAY = config.MAX_DETAIL_DELAY = 0.0
        scan.SOURCES = {"stating": self.StatingSource()}

    def tearDown(self):
        scan.SOURCES = self._sources
        config.MIN_DETAIL_DELAY, config.MAX_DETAIL_DELAY = self._delays
        super().tearDown()

    def _enrich_stated_job(self, worktype="remote", seniority="senior"):
        self.conn.execute(
            """INSERT INTO jobs (source, source_id, title, link, description,
                                 worktype, seniority)
               VALUES ('stating', '1', 'python developer', 'https://example.test/1', '',
                       :worktype, :seniority)""",
            {"worktype": worktype, "seniority": seniority},
        )
        self.conn.commit()
        scan.enqueue(self.conn, self.admin)
        state = scan.ScanState(self.conn, scan.claim_next(self.conn, "worker-1"))
        scan._enrich_phase(state, self.conn, None)
        return self.conn.execute(
            "SELECT worktype, seniority, skills, description FROM jobs WHERE source_id = '1'"
        ).fetchone()

    def test_a_field_the_board_stated_survives_the_description(self):
        row = self._enrich_stated_job()
        self.assertEqual(row["worktype"], "remote",
                         "the board said so on its card; the prose does not get a vote")

    def test_a_field_the_board_did_not_state_is_still_extracted(self):
        """`provides` is a list of what this board sets, not a blanket opt-out."""
        row = self._enrich_stated_job(seniority=None)
        self.assertEqual(row["seniority"], "senior", "read out of 'senior' in the prose")
        self.assertIn("python", row["skills"])
        self.assertTrue(row["description"], "and the description is always written")


# ── Where the shared crawl asks for ──────────────────────────

class CrawlRegionsTests(QueueTestCase):
    """Phase 8: the crawl narrows its request to where its users can work.

    The pool is shared by everybody, so the only honest answer is the union of
    every account's reach — and the load-bearing case is the *unplaceable* one:
    a user we cannot place has to empty the union entirely, because a narrowed
    crawl would never fetch into the shared pool the job they were owed.
    """

    def add_user(self, email, **settings):
        user_id = db.create_user(self.conn, email, "x")
        self.conn.commit()
        if settings:
            db.set_settings(self.conn, user_id, settings)
        return user_id

    def setUp(self):
        super().setUp()
        # The admin the harness creates has answered nothing, which is exactly
        # the "cannot be placed" case — give them a town so the other cases are
        # about the users the test actually adds.
        db.set_settings(self.conn, self.admin, {"user_location": "Bratislava"})

    def test_one_slovak_user_narrows_the_crawl_to_europe(self):
        self.assertEqual(db.crawl_regions(self.conn), {"SK", "EU"})
        self.assertEqual(places.covering_region(db.crawl_regions(self.conn)), "EU")

    def test_an_answered_preference_beats_the_town_it_was_derived_from(self):
        self.add_user("b@example.test", user_location="Bratislava",
                      user_regions=["NA"])
        self.assertEqual(db.crawl_regions(self.conn), {"SK", "EU", "NA"})
        self.assertIsNone(places.covering_region(db.crawl_regions(self.conn)))

    def test_a_user_nobody_can_place_widens_the_crawl_back_to_everywhere(self):
        self.add_user("nowhere@example.test")   # no town, no regions
        self.assertEqual(db.crawl_regions(self.conn), set())
        self.assertIsNone(places.covering_region(db.crawl_regions(self.conn)))

    def test_the_union_is_over_every_account(self):
        self.add_user("c@example.test", user_regions=["CZ"])
        self.add_user("d@example.test", user_regions=["PT", "ES"])
        self.assertEqual(db.crawl_regions(self.conn), {"SK", "EU", "CZ", "PT", "ES"})
        self.assertEqual(places.covering_region(db.crawl_regions(self.conn)), "EU")

    def test_an_instance_with_no_users_at_all_asks_for_everything(self):
        self.conn.execute("DELETE FROM user_settings")
        self.conn.execute("DELETE FROM users")
        self.conn.commit()
        self.assertEqual(db.crawl_regions(self.conn), set())

    def test_the_adapter_is_handed_the_regions_by_the_real_scan(self):
        """End to end: the wiring, not the query — an adapter that reads
        `ctx.regions` has to receive them from the process that scans."""
        seen = []
        source = FakeSource(count=0, listed=1, on_search=lambda ctx: seen.append(ctx.regions))
        db.set_settings(self.conn, self.admin, {"enabled_sources": ["fake"]})

        with mock.patch.dict(scan.SOURCES, {"fake": source}):
            scan.enqueue(self.conn, self.admin)
            scan.run_claimed(self.conn, scan.claim_next(self.conn, "worker-1"))

        self.assertEqual(seen, [frozenset({"SK", "EU"})])

    def test_the_crawl_does_not_narrow_to_whoever_pressed_the_button(self):
        """Where is the one setting the crawl does *not* take from the admin.

        Everything else about a scan is the admin's (terms, boards, window),
        because the pool is shared — which is the same reason `where` cannot be
        theirs: their answer is not the other accounts' answer.
        """
        self.add_user("canadian@example.test", user_regions=["CA"])
        seen = []
        source = FakeSource(count=0, listed=1, on_search=lambda ctx: seen.append(ctx.regions))
        db.set_settings(self.conn, self.admin, {"enabled_sources": ["fake"]})

        with mock.patch.dict(scan.SOURCES, {"fake": source}):
            scan.enqueue(self.conn, self.admin)
            scan.run_claimed(self.conn, scan.claim_next(self.conn, "worker-1"))

        self.assertEqual(seen, [frozenset({"SK", "EU", "CA"})])
        self.assertIsNone(places.covering_region(seen[0]), "so no board is narrowed")


if __name__ == "__main__":
    unittest.main()

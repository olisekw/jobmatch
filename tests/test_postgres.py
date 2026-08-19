"""Postgres parity — the Phase 5 dialect gaps, run against a real server.

Skipped unless `TEST_DATABASE_URL` points at a Postgres database this suite may
**drop every table in**. CI sets it from a `postgres:16` service container; to
run it locally:

    docker run --rm -e POSTGRES_PASSWORD=x -p 5432:5432 postgres:16
    TEST_DATABASE_URL=postgresql://postgres:x@localhost:5432/postgres \
        python3 -m pytest tests/test_postgres.py -q

The rest of the suite is SQLite-only by construction — it patches
`config.DB_PATH` at a filesystem path — and that is fine: what needs a second
backend is not the scoring or the extraction, it is the handful of statements
whose *meaning* changes with the dialect. Those are what this file pins:

- the `datetime('now')` / `date('now')` schema defaults, which have to keep
  producing the same naive-UTC string shape every reader in `display.py` expects;
- NULL ordering, where SQLite and Postgres disagree by default;
- the queue's `INSERT … SELECT … WHERE NOT EXISTS … RETURNING` and its
  conditional-UPDATE claim;
- the settings upsert and `ensure_user_jobs`, the two `ON CONFLICT` / INSERT …
  SELECT statements outside `backfill.py` (which is SQLite-only by design);
- `init_schema` run by two processes at once, which is a cold `docker compose
  up` — `web` and `worker` both bootstrap.
"""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor

import sqlalchemy as sa

import config
from jobmatch import db, display, scan

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


# On the base class, so the skip is inherited by every case below — this has to
# work under `unittest discover` as well as pytest, which rules out pytestmark.
@unittest.skipUnless(
    TEST_DATABASE_URL.startswith("postgresql"),
    "set TEST_DATABASE_URL to a disposable Postgres database to run these",
)
class PostgresTestCase(unittest.TestCase):
    """A fresh schema per test, on the real server."""

    @classmethod
    def setUpClass(cls):
        cls._orig = (config.DB_PATH, config.DATABASE_URL)
        # DB_PATH is what `db._url()` prefers; None is how a non-sqlite
        # DATABASE_URL reaches it, exactly as `config` computes it at import.
        config.DB_PATH = None
        config.DATABASE_URL = TEST_DATABASE_URL

    @classmethod
    def tearDownClass(cls):
        config.DB_PATH, config.DATABASE_URL = cls._orig

    def setUp(self):
        engine = db.get_engine()
        db.metadata.drop_all(engine, checkfirst=True)
        self.conn = db.get_conn()
        self.addCleanup(self.conn.close)
        db.init_schema(self.conn)
        self.assertEqual(self.conn.dialect, "postgresql")

    # ── helpers ──────────────────────────────────────────────

    def a_user(self, email="a@example.com", is_admin=True):
        user_id = db.create_user(self.conn, email, is_admin=is_admin)
        self.conn.commit()
        return user_id

    def a_job(self, source_id, **overrides):
        params = {
            "source": "fake", "source_id": source_id,
            "title": f"Job {source_id}", "company": "Co", "location": "Remote",
            "link": f"https://example.com/{source_id}", "posted_at": None,
        }
        params.update(overrides)
        job_id = self.conn.scalar(
            """INSERT INTO jobs (source, source_id, title, company, location, link,
                                 posted_at)
               VALUES (:source, :source_id, :title, :company, :location, :link,
                       :posted_at)
               RETURNING id""",
            params,
        )
        self.conn.commit()
        return job_id


class SchemaDefaultTests(PostgresTestCase):
    def test_timestamp_defaults_have_the_stored_shape(self):
        """A server default must be readable by `display.parse`, or dates break."""
        user_id = self.a_user()
        created = self.conn.scalar(
            "SELECT created_at FROM users WHERE id = :id", {"id": user_id}
        )
        self.assertRegex(created, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertIsNotNone(display.parse(created))
        # Naive UTC, not local time: within a minute of what Python calls now.
        self.assertLess(
            abs((display.utcnow() - display.parse(created)).total_seconds()), 60
        )

    def test_date_default_is_a_date(self):
        user_id = self.a_user()
        job_id = self.a_job("d1")
        self.conn.execute(
            "INSERT INTO applications (user_id, job_id) VALUES (:u, :j)",
            {"u": user_id, "j": job_id},
        )
        self.conn.commit()
        applied = self.conn.scalar("SELECT applied_at FROM applications")
        self.assertRegex(applied, r"^\d{4}-\d{2}-\d{2}$")

    def test_scans_accepts_queued(self):
        # SQLite's answer comes from reading the CHECK constraint back; Postgres
        # gets the current schema from create_all and is True by construction.
        self.assertTrue(db.scans_accepts_queued(self.conn))

    def test_init_schema_is_idempotent(self):
        db.init_schema(self.conn)
        db.init_schema(self.conn)
        tables = set(sa.inspect(self.conn.sa).get_table_names())
        self.assertTrue({t.name for t in db.metadata.sorted_tables} <= tables)

    def test_two_processes_bootstrap_at_once(self):
        """A cold `docker compose up`: `web` and `worker` both call init_schema."""
        db.metadata.drop_all(db.get_engine(), checkfirst=True)

        def bootstrap():
            with db.get_conn() as conn:
                db.init_schema(conn)
            return True

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = [f.result() for f in [pool.submit(bootstrap) for _ in range(4)]]
        self.assertEqual(results, [True] * 4)
        tables = set(sa.inspect(self.conn.sa).get_table_names())
        self.assertIn("scans", tables)


class OrderingTests(PostgresTestCase):
    def test_unscored_jobs_sort_last(self):
        """The gap this exists for: Postgres sorts NULL *first* on DESC."""
        user_id = self.a_user()
        low, high, unscored = (self.a_job("low"), self.a_job("high"),
                               self.a_job("unscored"))
        db.ensure_user_jobs(self.conn, user_id)
        for job_id, score in ((low, 10.0), (high, 90.0), (unscored, None)):
            self.conn.execute(
                "UPDATE user_jobs SET match_score = :score "
                "WHERE user_id = :u AND job_id = :j",
                {"score": score, "u": user_id, "j": job_id},
            )
        self.conn.commit()

        def ids(order):
            return [
                row["id"] for row in self.conn.execute(
                    f"""SELECT j.id FROM jobs j
                        JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = :u
                        ORDER BY {order}""",
                    {"u": user_id},
                )
            ]

        self.assertEqual(ids(db.JOB_ORDER["score"]), [high, low, unscored])
        # And the same query without the clause, to show the gap is real rather
        # than theoretical — if this ever matches, the NULLS LAST can go.
        self.assertEqual(
            ids("uj.match_score DESC"), [unscored, high, low]
        )


class QueueTests(PostgresTestCase):
    def test_enqueue_claim_and_finish(self):
        user_id = self.a_user()
        state, error = scan.enqueue(self.conn, user_id=user_id, trigger="manual")
        self.assertIsNone(error)
        self.assertEqual(state["status"], "queued")

        # The guard is inside the INSERT: a second enqueue matches nothing.
        again, error = scan.enqueue(self.conn, user_id=user_id)
        self.assertIsNone(again)
        self.assertEqual(error, "A scan is already running.")

        claimed = scan.claim_next(self.conn, "worker-1")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["trigger"], "manual")
        self.assertIsNone(scan.claim_next(self.conn, "worker-2"))

        self.assertTrue(scan.request_stop(self.conn))
        self.assertTrue(scan.current_status(self.conn)["cancelling"])

    def test_reconcile_orphans_closes_a_silent_row(self):
        self.a_user()
        scan.enqueue(self.conn, trigger="schedule")
        scan.claim_next(self.conn, "worker-1")
        # Nothing has heartbeat since the claim, so a zero-second staleness
        # window is the "the worker running this is gone" case.
        self.assertEqual(scan.reconcile_orphans(self.conn, stale_seconds=0), 1)
        self.assertEqual(scan.current_status(self.conn)["status"], "failed")
        # …and the queue is usable again.
        _state, error = scan.enqueue(self.conn)
        self.assertIsNone(error)


class WriteStatementTests(PostgresTestCase):
    def test_settings_upsert(self):
        user_id = self.a_user()
        db.set_setting(self.conn, user_id, "scan_days", 3)
        db.set_setting(self.conn, user_id, "scan_days", 9)
        self.assertEqual(db.get_setting(self.conn, user_id, "scan_days"), 9)
        self.assertEqual(
            self.conn.scalar(
                "SELECT COUNT(*) FROM user_settings WHERE user_id = :u AND key = 'scan_days'",
                {"u": user_id},
            ),
            1,
        )

    def test_ensure_user_jobs_is_incremental(self):
        user_id = self.a_user()
        self.a_job("j1")
        self.a_job("j2")
        self.assertEqual(db.ensure_user_jobs(self.conn, user_id), 2)
        self.assertEqual(db.ensure_user_jobs(self.conn, user_id), 0)
        self.a_job("j3")
        self.assertEqual(db.ensure_user_jobs(self.conn, user_id), 1)

    def test_job_insert_ignores_a_duplicate(self):
        self.a_job("dupe")
        inserted = self.conn.execute(
            """INSERT INTO jobs (source, source_id, title, link)
               VALUES ('fake', 'dupe', 'Again', 'https://example.com/dupe')
               ON CONFLICT (source, source_id) DO NOTHING""",
        ).rowcount
        self.conn.commit()
        self.assertEqual(inserted, 0)

    def test_delete_user_leaves_the_shared_pool(self):
        user_id = self.a_user()
        self.a_job("shared")
        db.ensure_user_jobs(self.conn, user_id)
        scan.enqueue(self.conn, user_id=user_id)
        db.delete_user(self.conn, user_id)
        self.assertEqual(self.conn.scalar("SELECT COUNT(*) FROM jobs"), 1)
        self.assertEqual(self.conn.scalar("SELECT COUNT(*) FROM user_jobs"), 0)
        self.assertEqual(self.conn.scalar("SELECT COUNT(*) FROM scans"), 1)


if __name__ == "__main__":
    unittest.main()

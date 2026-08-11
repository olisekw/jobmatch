"""Tests for replaying extraction over stored rows (`jobmatch.reextract`).

The load-bearing rule here is the CLAUDE.md invariant "a source's structured
fields beat regex extraction". At insert time `scan._insert_stub` enforces it by
preferring a present stub value; afterwards the two are indistinguishable in the
DB, so `reextract` has to rely on each adapter's `provides` declaration instead.
`test_source_provided_worktype_is_not_overwritten` is the guard for that — it is
what stops a re-extract from quietly rewriting a remote board's jobs to hybrid.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import tempfile
import unittest
from pathlib import Path

import config
from jobmatch import db, reextract
from jobmatch.sources import SOURCES

# An ad whose Slovak text regex-extracts as hybrid (explicitly partial WFH).
HYBRID_AD = "Programátor, 50% práce z domu, plný úväzok. Python a React."


class ReextractTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_path = config.DB_PATH
        config.DB_PATH = Path(self._tmp.name) / "test.db"
        self.conn = db.get_conn()
        db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        config.DB_PATH = self._orig_db_path
        self._tmp.cleanup()

    def _insert(self, source, source_id, **cols):
        params = dict(cols, source=source, source_id=source_id,
                      link=f"http://x/{source_id}", description=HYBRID_AD)
        keys = ["source", "source_id", "link", "description"] + list(cols)
        self.conn.execute(
            "INSERT INTO jobs ({}) VALUES ({})".format(
                ", ".join(keys), ", ".join(f":{k}" for k in keys)),
            params,
        )
        self.conn.commit()

    def _worktype(self, source_id):
        return self.conn.execute(
            "SELECT worktype FROM jobs WHERE source_id = :source_id",
            {"source_id": source_id},
        ).fetchone()["worktype"]

    def test_source_provided_worktype_is_not_overwritten(self):
        # remoteok declares worktype in `provides`: its stored "remote" is the
        # board's own answer and must survive, even though this text reads hybrid.
        self.assertIn("worktype", SOURCES["remoteok"].provides)
        self._insert("remoteok", "r1", worktype="remote")
        reextract.main(["--apply"])
        self.assertEqual(self._worktype("r1"), "remote")

    def test_regex_only_source_is_recomputed(self):
        # profesia declares nothing, so its worktype is regex-derived and updates.
        self.assertEqual(SOURCES["profesia"].provides, frozenset())
        self._insert("profesia", "p1", worktype="remote")
        reextract.main(["--apply"])
        self.assertEqual(self._worktype("p1"), "hybrid")

    def test_dry_run_writes_nothing(self):
        self._insert("profesia", "p2", worktype="remote")
        reextract.main([])
        self.assertEqual(self._worktype("p2"), "remote")

    def test_is_idempotent(self):
        self._insert("profesia", "p3", worktype="remote")
        reextract.main(["--apply"])
        updates, _ = reextract._recompute(self.conn)
        self.assertEqual(updates, [])

    def test_unregistered_source_is_left_alone(self):
        # A board that's no longer in the registry: we can't know what it
        # supplied, so nothing structured is touched.
        self._insert("gone", "g1", worktype="remote")
        reextract.main(["--apply"])
        self.assertEqual(self._worktype("g1"), "remote")

    def test_empty_descriptions_are_skipped(self):
        self.conn.execute(
            "INSERT INTO jobs (source, source_id, link, description, worktype) "
            "VALUES ('profesia', 'p4', 'http://x/p4', '', 'remote')")
        self.conn.commit()
        reextract.main(["--apply"])
        self.assertEqual(self._worktype("p4"), "remote")

    def test_user_status_is_preserved(self):
        # Triage lives in user_jobs now, so this crosses the tenancy boundary:
        # the shared `jobs` row is rewritten while the user's own row is not.
        self._insert("profesia", "p5", worktype="remote")
        user_id = db.create_user(self.conn, "a@example.com")
        db.ensure_user_jobs(self.conn, user_id)
        self.conn.execute("UPDATE user_jobs SET status = 'declined'")
        self.conn.commit()

        reextract.main(["--apply"])

        self.assertEqual(self._worktype("p5"), "hybrid")   # derived, updated
        status = self.conn.scalar(
            "SELECT status FROM user_jobs WHERE user_id = :user_id", {"user_id": user_id})
        self.assertEqual(status, "declined")               # user-owned, untouched

    def test_one_users_triage_does_not_leak_into_another(self):
        self._insert("profesia", "p6", worktype="remote")
        first = db.create_user(self.conn, "first@example.com")
        second = db.create_user(self.conn, "second@example.com")
        for user_id in (first, second):
            db.ensure_user_jobs(self.conn, user_id)
        self.conn.execute(
            "UPDATE user_jobs SET status = 'applied' WHERE user_id = :user_id",
            {"user_id": first},
        )
        self.conn.commit()

        reextract.main(["--apply"])

        statuses = {
            row["user_id"]: row["status"]
            for row in self.conn.execute("SELECT user_id, status FROM user_jobs")
        }
        self.assertEqual(statuses, {first: "applied", second: "new"})


if __name__ == "__main__":
    unittest.main()

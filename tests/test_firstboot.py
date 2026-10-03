"""Tests for what happens the first time this is started on a box.

Everything here was *measured* on a real four-container first boot before it was
written down (Phase 9 item 5) — `cp .env.example .env`, fill in DEPLOY.md §2's
table, `docker compose up -d --build --wait` — and every guard was made to fail
before it was trusted:

- **The two startup refusals turn a first boot red.** A blank `SECRET_KEY` and
  the `JOBMATCH_DEBUG=1` that `.env.example` ships both made gunicorn's worker
  fail to boot and `docker compose up --wait` exit **1** with `web is
  unhealthy`, rather than quietly serving the internet with the dev key. They
  fired with `HOST` still at the example's `127.0.0.1`, because `wsgi.py` says
  `deployed=True` rather than asking what the app is bound to.
- **`mark_deployed()` is what puts `Secure` on the session cookie**, and that is
  not incidental: with `HOST=127.0.0.1` — what `.env.example` ships, and
  harmless under gunicorn, which binds with `--bind` — the container reported
  `config.SESSION_COOKIE_SECURE = False` and the cookie came back `Secure`
  anyway. Commenting the one call out of `wsgi.py` and restarting dropped
  `Secure` from the header, which is the whole reason that file exists.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import pathlib
import re
import tempfile
import unittest
from unittest import mock

import config

config.RATELIMIT_ENABLED = False
# `check_runtime_config` refuses a deployment whose `.env` is being ignored, and
# whether the interpreter running the suite happens to have python-dotenv
# installed is not what any test below is about. `IgnoredDotenvTests` turns it
# back on for itself, explicitly.
config.DOTENV_IGNORED = False

import app as webapp  # noqa: E402
from jobmatch import backfill, db  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_EXAMPLE = (ROOT / ".env.example").read_text()
WSGI = (ROOT / "wsgi.py").read_text()
DOCKERFILE = (ROOT / "Dockerfile").read_text()
COMPOSE_TEXT = (ROOT / "docker-compose.yml").read_text()
WORKER_SRC = (ROOT / "jobmatch/worker.py").read_text()

# Read by `jobmatch/obs.py`, and set per container in docker-compose.yml so that
# `web` and `worker` can be told apart in one log stream. `.env.example` says so
# in prose rather than offering it as a value, because setting it in `.env`
# would label both containers the same.
SET_BY_COMPOSE = {"JOBMATCH_COMPONENT"}


def declared_in_example():
    """Every name `.env.example` offers, commented-out ones included."""
    return set(re.findall(r"(?m)^\s*#?\s*([A-Z][A-Z_0-9]+)=", ENV_EXAMPLE))


def env_names_read_by_the_code():
    """Every environment variable any shipped module actually reads."""
    names = set()
    for path in sorted(ROOT.glob("*.py")) + sorted(ROOT.glob("jobmatch/*.py")):
        src = path.read_text()
        direct = r"""os\.environ(?:\.get)?[\(\[]\s*["']([A-Z][A-Z_0-9]+)["']"""
        names |= set(re.findall(direct, src))
        names |= set(re.findall(r"""_env_\w+\(\s*["']([A-Z][A-Z_0-9]+)["']""", src))
    return names


class EnvExampleTests(unittest.TestCase):
    """`.env.example` is the whole of a deployer's first boot: they copy it.

    A variable the code reads but the file never mentions is one nobody knows
    exists, and its default is then a decision made by whoever wrote the line
    rather than by whoever runs the box.
    """

    def test_every_variable_the_code_reads_is_offered_by_the_example(self):
        missing = sorted(env_names_read_by_the_code() - declared_in_example() - SET_BY_COMPOSE)
        self.assertEqual(missing, [], f"not in .env.example: {missing}")

    def test_every_variable_compose_interpolates_is_offered_too(self):
        # `${FOO:?...}` stops the stack with a message, `${FOO:-default}` does
        # not — either way the deployer only learns the name from this file.
        used = set(re.findall(r"\$\{([A-Z][A-Z_0-9]+)[:?}-]", COMPOSE_TEXT))
        missing = sorted(used - declared_in_example())
        self.assertEqual(missing, [], f"compose reads, .env.example omits: {missing}")

    def test_the_example_still_ships_debug_on_and_deploy_md_still_says_to_turn_it_off(self):
        """The one line in the file whose shipped value is wrong for a box.

        It is right for `python3 app.py`, which is what the file is otherwise
        for, and it cannot quietly be wrong on a deployment because
        `check_runtime_config` refuses it — measured, `up --wait` exits 1. If
        this ever flips to off, DEPLOY.md's table has a row it no longer needs.
        """
        self.assertRegex(ENV_EXAMPLE, r"(?m)^JOBMATCH_DEBUG=1$")
        deploy_md = (ROOT / "DEPLOY.md").read_text()
        self.assertIn("`JOBMATCH_DEBUG`", deploy_md)


class RefusalTests(unittest.TestCase):
    """`check_runtime_config` is the only thing between a hurried `.env` and a
    session cookie the whole internet can forge."""

    def setUp(self):
        self._orig = (config.SECRET_KEY, config.DEBUG, config.IS_LOOPBACK)
        self._conc = (
            config.WEB_CONCURRENCY,
            config.RATELIMIT_STORAGE_URI,
            config.RATELIMIT_ENABLED,
        )

    def tearDown(self):
        config.SECRET_KEY, config.DEBUG, config.IS_LOOPBACK = self._orig
        (
            config.WEB_CONCURRENCY,
            config.RATELIMIT_STORAGE_URI,
            config.RATELIMIT_ENABLED,
        ) = self._conc

    def test_the_dev_key_is_refused_on_a_deployment(self):
        config.SECRET_KEY = config.DEV_SECRET_KEY
        config.DEBUG = False
        with self.assertRaises(RuntimeError) as caught:
            webapp.check_runtime_config(deployed=True)
        self.assertIn("SECRET_KEY", str(caught.exception))

    def test_debug_is_refused_on_a_deployment(self):
        config.SECRET_KEY = "a-real-key"
        config.DEBUG = True
        with self.assertRaises(RuntimeError) as caught:
            webapp.check_runtime_config(deployed=True)
        self.assertIn("JOBMATCH_DEBUG", str(caught.exception))

    def test_a_real_key_with_debug_off_is_accepted(self):
        config.SECRET_KEY = "a-real-key"
        config.DEBUG = False
        webapp.check_runtime_config(deployed=True)     # must not raise

    def test_the_dev_key_is_fine_on_loopback(self):
        config.SECRET_KEY = config.DEV_SECRET_KEY
        config.DEBUG = True
        config.IS_LOOPBACK = True
        webapp.check_runtime_config()                  # derives `deployed` itself
        webapp.check_runtime_config(deployed=False)

    def test_without_an_argument_it_asks_what_the_app_is_bound_to(self):
        config.SECRET_KEY = config.DEV_SECRET_KEY
        config.DEBUG = False
        config.IS_LOOPBACK = False
        with self.assertRaises(RuntimeError):
            webapp.check_runtime_config()


class WebConcurrencyRefusalTests(unittest.TestCase):
    """A second web process silently doubles the limits the first one enforces.

    `RATELIMIT_STORAGE_URI` defaults to `memory://`, which is one bucket *per
    process*. The image shipped `--workers 2` for a year and nothing read that
    number back: measured through Caddy on the four-container stack, 30
    CSRF-valid POSTs against `/login`'s `10 per minute` got **20** through
    before the first 429 — and which worker a request landed on decided whether
    it counted at all. The count now lives in `WEB_CONCURRENCY`, where
    `config.py` can see it, precisely so this refusal is possible.
    """

    def setUp(self):
        self._orig = (
            config.WEB_CONCURRENCY,
            config.RATELIMIT_STORAGE_URI,
            config.RATELIMIT_ENABLED,
            config.SECRET_KEY,
            config.DEBUG,
        )
        config.SECRET_KEY = "a-real-key"
        config.DEBUG = False
        config.RATELIMIT_ENABLED = True

    def tearDown(self):
        (
            config.WEB_CONCURRENCY,
            config.RATELIMIT_STORAGE_URI,
            config.RATELIMIT_ENABLED,
            config.SECRET_KEY,
            config.DEBUG,
        ) = self._orig

    def test_two_processes_against_an_in_memory_limiter_are_refused(self):
        config.WEB_CONCURRENCY = 2
        config.RATELIMIT_STORAGE_URI = "memory://"
        with self.assertRaises(RuntimeError) as caught:
            webapp.check_runtime_config(deployed=True)
        self.assertIn("WEB_CONCURRENCY", str(caught.exception))

    def test_it_is_refused_on_loopback_too(self):
        """Unlike the other two, this is not about exposure: a limit that
        depends on which process answered is wrong wherever it runs."""
        config.WEB_CONCURRENCY = 2
        config.RATELIMIT_STORAGE_URI = "memory://"
        with self.assertRaises(RuntimeError):
            webapp.check_runtime_config(deployed=False)

    def test_one_process_against_an_in_memory_limiter_is_the_shipped_case(self):
        config.WEB_CONCURRENCY = 1
        config.RATELIMIT_STORAGE_URI = "memory://"
        webapp.check_runtime_config(deployed=True)     # must not raise

    def test_a_shared_store_is_what_unlocks_a_second_process(self):
        config.WEB_CONCURRENCY = 4
        config.RATELIMIT_STORAGE_URI = "redis://cache:6379"
        webapp.check_runtime_config(deployed=True)     # must not raise

    def test_limits_turned_off_entirely_are_nobody_s_business(self):
        config.WEB_CONCURRENCY = 2
        config.RATELIMIT_STORAGE_URI = "memory://"
        config.RATELIMIT_ENABLED = False
        webapp.check_runtime_config(deployed=True)     # must not raise


class ShippedCommandTests(unittest.TestCase):
    """What the image actually runs, which is the half a unit test can see.

    The refusal above only fires if the process count reaches `config.py`, and
    it only does that because the `CMD` passes no `--workers`: gunicorn defaults
    that setting to `int(os.environ.get("WEB_CONCURRENCY", 1))` — confirmed
    against gunicorn 26.2.0 in this image, not assumed. A `--workers` flag would
    win over the environment and leave the refusal reading a number nothing
    obeys, which is the original defect wearing a different hat.
    """

    def test_the_web_command_names_no_worker_count(self):
        cmd = re.search(r"(?ms)^CMD \[.*?\]$", DOCKERFILE).group(0)
        self.assertNotIn("--workers", cmd)
        self.assertNotIn("-w", cmd.split())

    def test_concurrency_is_threads_instead(self):
        """The property `--workers 2` was bought for: one slow request (a CV
        upload parsing a PDF inline, which `--timeout 120` is for) must not make
        the site look down. Threads keep it inside one limiter bucket."""
        cmd = re.search(r"(?ms)^CMD \[.*?\]$", DOCKERFILE).group(0)
        threads = re.search(r'"--threads", "(\d+)"', cmd)
        self.assertIsNotNone(threads, "the web CMD runs a single thread")
        self.assertGreater(int(threads.group(1)), 1)

    def test_the_thread_count_fits_the_connection_pool(self):
        """The ceiling is the pool, not the CPU count. Every request holds
        exactly one `g.db` connection for its whole life, and SQLAlchemy's
        default QueuePool is `pool_size=5` + `max_overflow=10`; ask for more
        threads than that and the surplus blocks on checkout rather than
        serving anything."""
        from sqlalchemy.pool import QueuePool

        cmd = re.search(r"(?ms)^CMD \[.*?\]$", DOCKERFILE).group(0)
        threads = int(re.search(r'"--threads", "(\d+)"', cmd).group(1))
        pool = db.get_engine().pool
        self.assertIsInstance(pool, QueuePool)
        ceiling = pool.size() + pool._max_overflow
        self.assertLessEqual(threads, ceiling, f"{threads} threads over {ceiling} connections")

    def test_the_example_offers_the_variable_the_refusal_reads(self):
        """Without a line in `.env.example` the count is set by whoever wrote
        gunicorn's default rather than by whoever runs the box."""
        self.assertRegex(ENV_EXAMPLE, r"(?m)^WEB_CONCURRENCY=1$")


class EngineCacheThreadingTests(unittest.TestCase):
    """`db._ENGINES` is a plain dict, and one process with several threads is a
    new question for it.

    Phase 4 declared several gunicorn workers safe because scan state lives in
    the `scans` row — an argument about *processes*, which says nothing about
    two requests inside one. Engines and pools are thread-safe; the cache around
    them was not, and two winners means two QueuePools of 5+10 against a thread
    count chosen for one.
    """

    def test_racing_threads_all_get_the_same_engine(self):
        import threading

        db._ENGINES.pop(db._url(), None)
        start = threading.Barrier(8)
        seen = []

        def grab():
            start.wait()
            seen.append(db.get_engine())

        threads = [threading.Thread(target=grab) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(seen), 8)
        self.assertEqual(len({id(e) for e in seen}), 1, "more than one engine was built")
        self.assertIs(seen[0], db._ENGINES[db._url()],
                      "the cached engine is not the one handed out")


class MarkDeployedTests(unittest.TestCase):
    """The one path `wsgi.py` exists for.

    gunicorn binds with `--bind` and never reads `HOST`, so a container whose
    `.env` still says `127.0.0.1` — which is what `.env.example` ships — looks
    like loopback to `config.py` and would hand out cookies without `Secure`
    over a public TLS connection. Measured on the stack, both ways.
    """

    def setUp(self):
        self._deployed = webapp._deployed
        self._wsgi_app = webapp.app.wsgi_app
        self._secure = webapp.app.config["SESSION_COOKIE_SECURE"]
        self._orig = (config.SECURE_COOKIE_WAS_SET, config.TRUSTED_PROXY_HOPS)
        webapp._deployed = False

    def tearDown(self):
        webapp._deployed = self._deployed
        webapp.app.wsgi_app = self._wsgi_app
        webapp.app.config["SESSION_COOKIE_SECURE"] = self._secure
        config.SECURE_COOKIE_WAS_SET, config.TRUSTED_PROXY_HOPS = self._orig

    def test_it_turns_the_secure_cookie_on(self):
        webapp.app.config["SESSION_COOKIE_SECURE"] = False   # what HOST=127.0.0.1 leaves
        config.SECURE_COOKIE_WAS_SET = False
        webapp.mark_deployed()
        self.assertTrue(webapp.app.config["SESSION_COOKIE_SECURE"])

    def test_an_explicit_setting_still_wins(self):
        """`SESSION_COOKIE_SECURE=false` is how gunicorn is run locally over
        http, where a Secure cookie would simply never come back."""
        webapp.app.config["SESSION_COOKIE_SECURE"] = False
        config.SECURE_COOKIE_WAS_SET = True
        webapp.mark_deployed()
        self.assertFalse(webapp.app.config["SESSION_COOKIE_SECURE"])

    def test_it_trusts_exactly_the_proxy_hops_it_was_told_about(self):
        config.TRUSTED_PROXY_HOPS = 1
        webapp.mark_deployed()
        self.assertIsNot(webapp.app.wsgi_app, self._wsgi_app, "ProxyFix is not installed")
        self.assertEqual(webapp.app.wsgi_app.x_for, 1)

    def test_no_proxy_means_no_proxyfix(self):
        """Nothing in front means X-Forwarded-For is whatever a caller typed,
        and honouring it would hand them any IP they like past the rate limits."""
        config.TRUSTED_PROXY_HOPS = 0
        webapp.mark_deployed()
        self.assertIs(webapp.app.wsgi_app, self._wsgi_app)

    def test_it_only_happens_once(self):
        config.TRUSTED_PROXY_HOPS = 1
        webapp.mark_deployed()
        once = webapp.app.wsgi_app
        webapp.mark_deployed()
        self.assertIs(webapp.app.wsgi_app, once, "ProxyFix stacked twice: two hops, not one")


class WsgiTests(unittest.TestCase):
    """Neither guard above runs unless this file calls it, and nothing else does
    — `python3 app.py` is the other entrypoint and is the loopback case."""

    def test_wsgi_refuses_bad_config_and_marks_itself_deployed(self):
        self.assertRegex(WSGI, r"(?m)^check_runtime_config\(deployed=True\)$")
        self.assertRegex(WSGI, r"(?m)^mark_deployed\(\)$")

    def test_wsgi_does_not_start_the_scan_worker(self):
        """One scanner per instance, not one per gunicorn worker."""
        self.assertNotIn("start_thread", WSGI)


if __name__ == "__main__":
    unittest.main()


class GhostAdminTests(unittest.TestCase):
    """A passwordless bootstrap account must not own the shared crawl.

    Found on the live instance on 2026-10-01, not by a test: `users` still held
    the pre-Phase-3 `local@jobmatch.local` row with an empty hash and
    `is_admin = 1`, so `db.admin_user_id` — "the lowest-id admin" — handed the
    crawl to it. Six months of scheduled scans ran on a persona nobody could log
    in as, and the real owner's board selection was read by nothing.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db = config.DB_PATH
        config.DB_PATH = pathlib.Path(self._tmp.name) / "test.db"
        self.conn = db.get_conn()
        db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        config.DB_PATH = self._orig_db
        self._tmp.cleanup()

    def emails_by_admin(self):
        return {
            row["email"]: row["is_admin"]
            for row in self.conn.execute("SELECT email, is_admin FROM users")
        }

    def test_ghost_loses_the_crawl_to_the_real_owner(self):
        ghost = db.create_user(self.conn, config.LOCAL_USER_EMAIL, is_admin=True)
        owner = db.create_user(self.conn, "me@example.test", "argon2-hash", is_admin=True)
        self.conn.commit()
        # The bug, stated: the lowest id wins and it is the one with no password.
        self.assertEqual(ghost, db.admin_user_id(self.conn))

        backfill.demote_ghost_admin(self.conn)
        self.conn.commit()

        self.assertEqual(owner, db.admin_user_id(self.conn))
        self.assertEqual(self.emails_by_admin()[config.LOCAL_USER_EMAIL], 0)

    def test_it_keeps_the_ghost_s_rows(self):
        """Demoted, never deleted — those rows are the single-user era's triage."""
        ghost = db.create_user(self.conn, config.LOCAL_USER_EMAIL, is_admin=True)
        db.create_user(self.conn, "me@example.test", "argon2-hash", is_admin=True)
        self.conn.commit()

        backfill.demote_ghost_admin(self.conn)
        self.conn.commit()

        self.assertIsNotNone(db.get_user(self.conn, ghost))

    def test_the_last_admin_is_never_demoted(self):
        """An unowned instance stops scanning — `due_for_scan` asks `has_admin`."""
        db.create_user(self.conn, config.LOCAL_USER_EMAIL, is_admin=True)
        self.conn.commit()

        backfill.demote_ghost_admin(self.conn)
        self.conn.commit()

        self.assertTrue(db.has_admin(self.conn))

    def test_running_twice_changes_nothing(self):
        db.create_user(self.conn, config.LOCAL_USER_EMAIL, is_admin=True)
        db.create_user(self.conn, "me@example.test", "argon2-hash", is_admin=True)
        self.conn.commit()

        backfill.demote_ghost_admin(self.conn)
        self.conn.commit()
        first = self.emails_by_admin()
        backfill.demote_ghost_admin(self.conn)
        self.conn.commit()

        self.assertEqual(first, self.emails_by_admin())


class IgnoredDotenvTests(unittest.TestCase):
    """A `.env` that cannot be read is loud, not silent.

    The same live instance: python-dotenv was absent from the interpreter running
    `app.py`, `config.py` caught the ImportError and passed, and a fully
    populated `.env` configured nothing — the app served on the built-in dev key
    while the file set a real one, and every edit to it changed nothing at all.
    """

    def test_a_deployment_refuses_to_boot_on_it(self):
        with mock.patch.object(config, "DOTENV_IGNORED", True):
            with self.assertRaises(RuntimeError) as caught:
                webapp.check_runtime_config(deployed=True)
        self.assertIn("python-dotenv", str(caught.exception))

    def test_a_laptop_is_warned_but_still_boots(self):
        with mock.patch.object(config, "DOTENV_IGNORED", True):
            with self.assertLogs("jobmatch", level="WARNING") as logged:
                webapp.check_runtime_config(deployed=False)
        self.assertIn("python-dotenv", "\n".join(logged.output))

    def test_both_entrypoints_say_it_the_same_way(self):
        """One wording, because two processes report the same silence."""
        self.assertIn("config.DOTENV_IGNORED_MESSAGE", WORKER_SRC)
        self.assertIn("config.DOTENV_IGNORED_MESSAGE", (ROOT / "app.py").read_text())

    def test_nothing_is_said_when_there_is_no_env_file(self):
        with mock.patch.object(config, "DOTENV_IGNORED", False):
            webapp.check_runtime_config(deployed=False)  # no assertion: must not raise


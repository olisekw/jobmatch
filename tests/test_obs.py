"""Tests for Phase 7's operational surface: /healthz and the JSON log format.

Both exist for a machine to read — an uptime monitor and a log search — which
is exactly the kind of contract that rots unnoticed, because no page breaks
when it does. So the shape is asserted, not just the happy path.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import json
import logging
import unittest

import config
from jobmatch import obs
from tests.test_auth import AuthTestCase, webapp


def record(**kwargs):
    """A LogRecord the way `log.info(...)` would build one."""
    extra = kwargs.pop("extra", {})
    rec = logging.LogRecord(
        name=kwargs.get("name", "jobmatch.test"),
        level=kwargs.get("level", logging.INFO),
        pathname=__file__,
        lineno=1,
        msg=kwargs.get("msg", "hello %s"),
        args=kwargs.get("args", ("world",)),
        exc_info=kwargs.get("exc_info"),
    )
    for key, value in extra.items():
        setattr(rec, key, value)
    return rec


class JsonFormatterTests(unittest.TestCase):
    def setUp(self):
        self.formatter = obs.JsonFormatter()

    def test_a_line_is_one_json_object_with_the_base_keys(self):
        payload = json.loads(self.formatter.format(record()))
        self.assertEqual(payload["message"], "hello world")
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "jobmatch.test")
        self.assertEqual(payload["component"], obs.COMPONENT)
        self.assertRegex(payload["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

    def test_extra_becomes_fields_rather_than_prose(self):
        """The whole reason for JSON: `extra=` is queryable, a %s is not."""
        payload = json.loads(self.formatter.format(record(extra={"scan_id": 7})))
        self.assertEqual(payload["scan_id"], 7)
        # And nothing logging put on the record leaks in as a field.
        for noise in ("msg", "args", "pathname", "levelno", "created"):
            self.assertNotIn(noise, payload)

    def test_an_exception_becomes_a_nested_error_object(self):
        try:
            raise ValueError("no such board")
        except ValueError:
            import sys

            payload = json.loads(self.formatter.format(record(exc_info=sys.exc_info())))
        self.assertEqual(payload["error"]["type"], "ValueError")
        self.assertEqual(payload["error"]["message"], "no such board")
        self.assertIn("Traceback", payload["error"]["traceback"])

    def test_something_unserialisable_is_stringified_not_raised(self):
        """A log call is the worst possible place to discover a TypeError."""
        payload = json.loads(self.formatter.format(record(extra={"conn": object()})))
        self.assertIn("object at 0x", payload["conn"])

    def test_outside_a_request_there_are_no_request_fields(self):
        payload = json.loads(self.formatter.format(record()))
        self.assertNotIn("path", payload)

    def test_inside_a_request_the_line_says_which_one(self):
        with webapp.app.test_request_context("/api/jobs?sort=score"):
            payload = json.loads(self.formatter.format(record()))
        self.assertEqual(payload["path"], "/api/jobs")
        self.assertEqual(payload["method"], "GET")


class SetupLoggingTests(unittest.TestCase):
    def setUp(self):
        self._root_handlers = logging.getLogger().handlers[:]
        self._state = (obs._configured, obs.COMPONENT, config.LOG_FORMAT)

    def tearDown(self):
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        for handler in self._root_handlers:
            root.addHandler(handler)
        obs._configured, obs.COMPONENT, config.LOG_FORMAT = self._state

    def test_it_replaces_handlers_rather_than_giving_up_like_basicConfig(self):
        """`basicConfig` no-ops once anything has added a handler — this must not."""
        logging.getLogger().addHandler(logging.NullHandler())
        config.LOG_FORMAT = "json"
        obs.setup_logging(component="worker", force=True)
        handlers = logging.getLogger().handlers
        self.assertEqual(len(handlers), 1)
        self.assertIsInstance(handlers[0].formatter, obs.JsonFormatter)
        self.assertEqual(obs.COMPONENT, "worker")

    def test_text_is_the_default_so_local_development_stays_readable(self):
        config.LOG_FORMAT = "text"
        obs.setup_logging(force=True)
        formatter = logging.getLogger().handlers[0].formatter
        self.assertNotIsInstance(formatter, obs.JsonFormatter)


class SentryTests(unittest.TestCase):
    def tearDown(self):
        config.SENTRY_DSN = ""

    def test_no_dsn_is_the_normal_case_and_starts_nothing(self):
        config.SENTRY_DSN = ""
        self.assertFalse(obs.init_sentry())


class HealthzTests(AuthTestCase):
    """The endpoint an uptime monitor polls — public, and honest about the DB."""

    def setUp(self):
        super().setUp()
        self.client = webapp.app.test_client()

    def test_it_answers_without_a_session(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["checks"]["database"], "ok")
        self.assertEqual(body["release"], config.RELEASE)

    def test_it_says_nothing_a_stranger_should_not_know(self):
        """Public means public: no counts, no versions, no error text."""
        body = self.client.get("/healthz").get_json()
        self.assertEqual(set(body), {"status", "release", "checks"})
        self.assertEqual(set(body["checks"]), {"database"})

    def test_a_dead_database_is_a_503_not_a_cheerful_200(self):
        """The failure this exists to catch: web is up, Postgres is not."""
        original = webapp.get_db

        class Broken:
            def scalar(self, *_a, **_kw):
                raise RuntimeError("connection refused")

        webapp.get_db = lambda: Broken()
        try:
            with self.assertLogs("jobmatch", level="ERROR"):
                res = self.client.get("/healthz")
        finally:
            webapp.get_db = original
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.get_json()["status"], "error")
        self.assertEqual(res.get_json()["checks"]["database"], "error")
        # The traceback goes to the log, never to the caller.
        self.assertNotIn("connection refused", res.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

"""Logging and error reporting — what a deployed instance needs to be watchable.

Two things live here, both shared by `app.py` and `jobmatch.worker` so the web
process and the scanner cannot end up describing themselves differently:

- `setup_logging()` — one handler on the root logger, either the human format
  or one JSON object per line. `docker compose logs` is the only place a
  deployed instance says anything, and a grep over free text stops working the
  moment two processes interleave.
- `init_sentry()` — optional and silent when unconfigured. Nothing in here is
  allowed to keep the app from starting: a monitoring dependency that can take
  the service down is worse than no monitoring at all.
"""

import json
import logging
import os
import sys
import traceback

import config

log = logging.getLogger("jobmatch.obs")

TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

# Which of the two processes this is. Both run the same image and write to the
# same log stream, so every line says which one it came from. The environment
# is how docker-compose labels them; `setup_logging(component=...)` is how an
# entrypoint that knows better says so.
COMPONENT = os.environ.get("JOBMATCH_COMPONENT") or "web"

# Everything `logging` puts on a record by itself. Whatever is left over came
# from a caller's `extra={...}`, and that is exactly what is worth emitting —
# `log.info("scan done", extra={"scan_id": 7})` becomes a field, not prose.
_STANDARD_FIELDS = frozenset(
    """args asctime created exc_info exc_text filename funcName levelname levelno
    lineno message module msecs msg name pathname process processName
    relativeCreated stack_info taskName thread threadName""".split()
)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with a stable set of keys.

    Stable matters more than complete: a log search that has to cope with a
    field being sometimes a string and sometimes absent is not much better than
    grep. Extras and request context are additive; the five base keys are
    always there.
    """

    def format(self, record):
        payload = {
            # UTC ISO-8601 with milliseconds — sortable as a string, which is
            # what every log search ends up doing with it.
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "component": COMPONENT,
        }
        if record.exc_info:
            exc_type, exc_value, tb = record.exc_info
            payload["error"] = {
                "type": getattr(exc_type, "__name__", str(exc_type)),
                "message": str(exc_value),
                "traceback": "".join(traceback.format_exception(exc_type, exc_value, tb)),
            }
        payload.update(_request_fields())
        for key, value in record.__dict__.items():
            if key not in _STANDARD_FIELDS and not key.startswith("_"):
                payload[key] = value
        # `default=str` rather than a crash: a log call is never the place to
        # discover that something is not JSON-serialisable.
        return json.dumps(payload, default=str)


def _request_fields():
    """Which request produced this line — empty outside a request.

    Imported lazily so the worker, which has no Flask app at all, does not pay
    for a request context it can never be in.
    """
    try:
        from flask import has_request_context, request
    except ImportError:  # pragma: no cover — flask is a hard dependency
        return {}
    if not has_request_context():
        return {}
    fields = {"method": request.method, "path": request.path}
    # The user, when there is one. Never the email: logs are the one place
    # personal data ends up copied to by accident, and an id is enough to join.
    try:
        from flask_login import current_user

        if current_user.is_authenticated:
            fields["user_id"] = current_user.id
    except Exception:  # pragma: no cover — no login manager on this app
        pass
    return fields


_configured = False


def setup_logging(component=None, force=False):
    """Configure the root logger once, for whichever entrypoint got here first.

    `logging.basicConfig` is a no-op if anything has already added a handler,
    which is how a library import can silently decide an app's log format. This
    replaces the root handlers instead, so the format is whatever config says.
    """
    global _configured, COMPONENT
    if component:
        COMPONENT = component
    if _configured and not force:
        return
    _configured = True

    handler = logging.StreamHandler(sys.stdout)
    if config.LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(TEXT_FORMAT))

    root = logging.getLogger()
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))


def init_sentry():
    """Start error reporting if it is configured. Returns True if it did.

    Unconfigured is the normal case — local development, the test suite, and any
    instance whose owner has not signed up for it. Not installed is also fine:
    `sentry-sdk` is in requirements.txt for the image, but this module refuses
    to make a crash reporter into a startup dependency.
    """
    if not config.SENTRY_DSN:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.warning("SENTRY_DSN is set but sentry-sdk is not installed — not reporting")
        return False
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        environment=config.SENTRY_ENVIRONMENT,
        release=config.RELEASE,
        traces_sample_rate=config.SENTRY_TRACES_SAMPLE_RATE,
        # Off deliberately. This app holds email addresses and uploaded CVs;
        # PII in a crash report is a data export nobody asked for, and the
        # `user_id` above is enough to find the account.
        send_default_pii=False,
    )
    sentry_sdk.set_tag("component", COMPONENT)
    log.info("sentry error reporting on (environment=%s)", config.SENTRY_ENVIRONMENT)
    return True

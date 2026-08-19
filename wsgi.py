"""Gunicorn entrypoint.

    gunicorn --bind 0.0.0.0:8000 wsgi:app

Import-time bootstrap keeps a fresh container from serving a schema-less DB.

Safe to run with several workers as of Phase 4: scan state lives in the `scans`
row rather than in module globals, so any process can answer a status poll. The
scanning itself belongs to `python3 -m jobmatch.worker`, which this file
deliberately does not start — one scanner per instance, not one per web worker.
"""

from app import app, bootstrap_db, check_runtime_config, mark_deployed

check_runtime_config(deployed=True)
mark_deployed()
bootstrap_db()

__all__ = ["app"]

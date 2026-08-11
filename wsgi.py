"""Gunicorn entrypoint.

    gunicorn --bind 0.0.0.0:8000 wsgi:app

Import-time bootstrap keeps a fresh container from serving a schema-less DB.
Note that scan state still lives in `jobmatch/scan.py` module globals, so this
is single-worker-only until the scan loop moves to its own process.
"""

from app import app, bootstrap_db, check_runtime_config

check_runtime_config(deployed=True)
bootstrap_db()

__all__ = ["app"]

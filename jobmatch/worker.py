"""The scan worker — the only process that scrapes.

    python3 -m jobmatch.worker

Runs the same image as the web app and loops over five jobs: claim the next
queued scan and run it, close out scans a dead worker left `running`, enqueue a
scheduled scan when the last one is older than `SCAN_INTERVAL_HOURS`, put the
public demo account back when its last reset is older than `DEMO_RESET_HOURS`,
and send each user the email digest of their new matches when theirs is older
than `DIGEST_INTERVAL_HOURS`.

**Scheduling is a query, not a timer.** "Is the newest scan older than the
interval?" survives a restart, cannot drift, and cannot double-fire if a second
worker is ever started — none of which is true of an in-process cron. It is the
same reasoning that made `scans` the queue, so there is no APScheduler here.

Scanning must not multiply per user: this process scans once for everybody, and
`app.api_scan_start` only lets an admin queue an extra run.
"""

import logging
import os
import signal
import socket
import threading
from datetime import timedelta

import config

from . import db, demo, digest, display, obs, scan

log = logging.getLogger("jobmatch.worker")

# Set by SIGTERM/SIGINT. A running scan polls it through `should_stop`, so a
# `docker compose stop` ends with a `cancelled` row rather than an orphan.
_shutdown = threading.Event()


def worker_id():
    """Who claimed a scan — for the log and for a human reading the row."""
    return f"{socket.gethostname()}:{os.getpid()}"


def due_for_scan(conn, now=None):
    """True if the schedule says it is time for another crawl."""
    if not config.SCAN_ENABLED or config.SCAN_INTERVAL_HOURS <= 0:
        return False
    # Nothing to scan *for* yet: a fresh instance with no owner has no search
    # settings either, and the crawl runs off the admin's. Asked as `has_admin`
    # rather than `admin_user_id is None`, because that one falls back to the
    # first account and on a demo-enabled box the first account is the demo,
    # created by this very worker seconds into the first boot — which is how a
    # real first boot came to crawl the boards on the demo persona's terms,
    # before the admin `setpassword` creates existed. The demo is never an
    # admin precisely so it cannot trigger the shared crawl; the schedule has
    # to honour that too, not just the button.
    if not db.has_admin(conn):
        return False
    last = conn.scalar("SELECT MAX(started_at) FROM scans")
    if last is None:
        return True  # never scanned: the pool is empty and every user sees it
    started = display.parse(last)
    if started is None:
        return True
    now = now or display.utcnow()
    return now - started >= timedelta(hours=config.SCAN_INTERVAL_HOURS)


def maybe_schedule(conn):
    """Queue the scheduled scan if one is due. Returns its id, or None."""
    if not due_for_scan(conn):
        return None
    # Attributed to the admin: `scans.matched` is one number for a per-user
    # quantity, and the admin's dashboard is where it gets read.
    state, error = scan.enqueue(conn, user_id=db.admin_user_id(conn), trigger="schedule")
    if error:
        # Something is already queued or running — the schedule is satisfied.
        return None
    return state["scan_id"]


def maybe_reset_demo(conn):
    """Put the demo account back if it is due. Never fatal to the loop.

    Scheduled the same way scans are — a query, not a timer — so it is the
    worker's idle pass that notices, and a box that was off overnight resets
    once when it comes back rather than not at all. Wrapped because a broken
    demo is a cosmetic problem and must not stop the thing that scrapes.
    """
    try:
        return demo.maybe_reset(conn)
    except Exception:
        log.exception("demo reset failed — carrying on")
        return None


def maybe_send_digests(conn):
    """Send any email digest that is due. Never fatal to the loop.

    Here rather than in the web tier for the same reason scanning is: a digest
    is work nobody is waiting on a page for, and it wants the one process that
    is allowed to take minutes. `digest.send_due` already swallows a single
    user's failure; this catches the rest — a mail server having a bad night
    must not stop the thing that scrapes.
    """
    try:
        return digest.maybe_send(conn)
    except Exception:
        log.exception("sending digests failed — carrying on")
        return []


def run(poll_seconds=None, once=False):
    """The worker loop. `once` does a single pass, which is what tests want."""
    poll = poll_seconds if poll_seconds is not None else config.WORKER_POLL_SECONDS
    if config.DOTENV_IGNORED:
        # Said here too, not only in the web tier: this is the process `.env`
        # configures most — the scan interval, the SMTP host the digest needs,
        # the demo reset — and it is the one that runs for days unattended.
        log.warning("%s", config.DOTENV_IGNORED_MESSAGE)
    with db.get_conn() as conn:
        # The worker may well be the first process to reach a fresh database.
        db.init_schema(conn)
        if not db.scans_accepts_queued(conn):
            log.error(
                "this database predates the scan queue — run "
                "`python3 -m jobmatch.backfill`, or nothing can be queued"
            )
        # Reconciliation lives here, not in the web app's boot: a web process
        # restarting says nothing about whether a scan is still running, while
        # a missing heartbeat says exactly that.
        scan.reconcile_orphans(conn)
    log.info(
        "worker %s up — polling every %ss, scheduled scans %s",
        worker_id(), poll,
        f"every {config.SCAN_INTERVAL_HOURS}h" if config.SCAN_INTERVAL_HOURS > 0
        and config.SCAN_ENABLED else "off",
    )

    try:
        while not _shutdown.is_set():
            # A connection per pass, not one for the life of the process. Against
            # a file that was free; against a Postgres container it means an idle
            # connection dropped overnight is a fresh checkout next tick (the
            # pool pre-pings) rather than an OperationalError at 4am. A claimed
            # scan keeps its connection for the whole run, which is minutes of
            # continuous use — exactly the case that never goes stale.
            with db.get_conn() as conn:
                claimed = scan.claim_next(conn, worker_id())
                if claimed is not None:
                    log.info("claimed scan %d (%s)", claimed["id"], claimed["trigger"])
                    result = scan.run_claimed(conn, claimed, should_stop=_shutdown.is_set)
                    log.info(
                        "scan %d %s — %d found, %d enriched, %d could not be read",
                        claimed["id"], result["status"], result["found"],
                        result["enriched"], result["failed"],
                    )
                    if once:
                        break
                    continue  # straight back for the next one, no poll delay

                scan.reconcile_orphans(conn)
                maybe_schedule(conn)
                maybe_reset_demo(conn)
                maybe_send_digests(conn)
            if once:
                break
            _shutdown.wait(poll)
    finally:
        log.info("worker %s stopped", worker_id())


def start_thread():
    """Run the loop inside this process — the local `python3 app.py` path.

    Never called by `wsgi.py`: under gunicorn each web process would start its
    own, and several of them scraping the same boards is the thing Phase 4
    exists to stop. In a deployment the worker is its own container.
    """
    thread = threading.Thread(target=run, name="scan-worker", daemon=True)
    thread.start()
    return thread


def _request_shutdown(signum, _frame):
    if _shutdown.is_set():
        log.warning("signal %d again — already stopping", signum)
        return
    log.info("signal %d — finishing the current step, then stopping", signum)
    _shutdown.set()


def main():
    obs.setup_logging(component="worker")
    obs.init_sentry()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _request_shutdown)
    run()


if __name__ == "__main__":
    main()

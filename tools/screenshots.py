"""Regenerate the screenshots the landing page, the README and the dashboard's
tutorial modal show.

    python3 tools/screenshots.py                 # from a copy of data/jobmatch.db
    python3 tools/screenshots.py --synthetic     # from made-up jobs, no real DB needed

Writes `static/screens/<page>.png` and `<page>-dark.png` — one pair per page, so
the landing page and GitHub can each pick the scheme the reader is already in —
and `static/screens/tutorial/<NN-name>(-dark).png`, cropped to one element each.

Nothing here touches the real database, and neither set of images is the real
user's own data. The main pass seeds and photographs the public demo account
(`jobmatch.demo`), whose profile and tracker rows are a fixed, fabricated seed
meant to be shown to strangers. The tutorial pass runs a *second*, separate
scratch instance in local-no-auth mode (the same thing a `python3 app.py` on a
laptop with no deployment is) so the "Scan job boards" button — gated on
`can_scan`, which the demo account deliberately never has — is actually there
to photograph; it seeds a small amount of its own made-up profile/tracker data
directly, rather than reusing the demo's.

Both run against a `.backup()`-copied scratch `DATA_DIR`, with the app started
as a subprocess — the same `python3 app.py` a developer runs, so what gets
photographed is the actual entrypoint and not a test client's idea of it.

Needs Playwright's Chromium, which the Profesia adapter already requires:

    playwright install chromium
"""

import argparse
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT_DIR = REPO / "static" / "screens"
LIVE_DB = REPO / "data" / "jobmatch.db"

# (filename, path, what to do before the shot)
PAGES = [
    ("dashboard", "/", None),
    ("jobs", "/jobs", "open_breakdown"),
    ("tracker", "/tracker", None),
    ("settings", "/settings", None),
]

VIEWPORT = {"width": 1280, "height": 900}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def copy_live_db(dest):
    """A consistent copy of the live database, WAL and all.

    `.backup()` rather than `cp`: the file may have an open WAL, and copying
    the three files by hand is how you get a torn snapshot.
    """
    src = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    out = sqlite3.connect(dest)
    with out:
        src.backup(out)
    src.close()
    out.close()


def synthetic_jobs(conn):
    """A pool to photograph when there is no real database to copy."""
    from jobmatch import places  # after prepare() has pointed config at the copy

    titles = [
        ("Senior React Developer", "Bratislava", "remote", "senior"),
        ("Python Backend Engineer", "Košice", "hybrid", "medior"),
        ("Full-stack Developer (Node/React)", "Bratislava", "remote", "medior"),
        ("Frontend Developer — TypeScript", "Anywhere in Europe", "remote", "medior"),
        ("Junior Web Developer", "Žilina", "onsite", "junior"),
        ("DevOps Engineer", "USA only", "remote", "senior"),
        ("Software Engineer, Platform", "Brno", "hybrid", None),
        ("React Native Developer", "Worldwide", "remote", "medior"),
        ("Data Engineer (Python, SQL)", "Bratislava", None, "senior"),
        ("Graduate Software Developer", "Nitra", "onsite", "junior"),
    ]
    for i, (title, location, worktype, seniority) in enumerate(titles * 4):
        conn.execute(
            """INSERT INTO jobs (source, source_id, title, company, location, link,
                                 description, skills, worktype, seniority,
                                 employment_type, salary_min, salary_max,
                                 salary_currency, salary_period, country)
               VALUES (:source, :source_id, :title, :company, :location, :link,
                       :description, :skills, :worktype, :seniority,
                       :employment_type, :smin, :smax, :cur, :per, :country)""",
            {
                "source": ["remoteok", "remotive", "profesia", "kariera"][i % 4],
                "source_id": f"demo-{i}",
                "title": title,
                "company": f"Example {chr(65 + i % 20)} s.r.o.",
                "location": location,
                "link": f"https://example.com/jobs/{i}",
                "description": (
                    f"We are looking for a {title}. You will work with React, "
                    "TypeScript and Node.js on a PostgreSQL back end, in a team "
                    "that ships every week. Docker and Git-based CI. "
                    "Práca z domu je možná."
                ),
                "skills": "react,typescript,node.js,python,postgresql,docker,git",
                "worktype": worktype,
                "seniority": seniority,
                "employment_type": "fulltime",
                # Every third posting quotes nothing, which is roughly the
                # real ratio and is the case the Jobs page has to look right in.
                "smin": None if i % 3 == 2 else 2200 + (i % 7) * 250,
                "smax": None if i % 3 == 2 else 3200 + (i % 7) * 250,
                "cur": None if i % 3 == 2 else "EUR",
                "per": None if i % 3 == 2 else "month",
                "country": places.country(
                    ["remoteok", "remotive", "profesia", "kariera"][i % 4], location),
            },
        )
    conn.commit()


TUTORIAL_DIR = OUT_DIR / "tutorial"

# (filename stem, path, element to crop to, cap on the crop's height in px)
TUTORIAL_SHOTS = [
    ("01-resume", "/settings", ".dropzone", 200),
    ("02-skills", "/settings", "#skill-categories", 460),
    ("03-scan", "/", "#scan-panel", 200),
    ("04-jobs", "/jobs", "#job-list", 440),
    ("05-tracker", "/tracker", ".tracker-table", 440),
]


def prepare(data_dir, synthetic):
    """A scratch DATA_DIR with a seeded demo account in it. Returns nothing."""
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["DATABASE_URL"] = f"sqlite:///{data_dir / 'jobmatch.db'}"
    os.environ["DEMO_MODE"] = "true"

    if not synthetic:
        if not LIVE_DB.exists():
            raise SystemExit(f"no {LIVE_DB} to copy — pass --synthetic")
        copy_live_db(data_dir / "jobmatch.db")

    import config  # imported here: it reads the environment set above

    config.DATA_DIR = data_dir
    config.RESUME_DIR = data_dir / "resumes"
    config.DB_PATH = data_dir / "jobmatch.db"
    config.DEMO_MODE = True

    from jobmatch import db, demo

    conn = db.get_conn()
    db.init_schema(conn)
    if synthetic:
        synthetic_jobs(conn)
    summary = demo.reset(conn)
    conn.close()
    print(f"seeded: {summary}")


def prepare_tutorial(data_dir, synthetic):
    """A separate scratch DATA_DIR for the tutorial modal's own screenshots.

    Not the demo account: the demo is deliberately never an admin
    (`jobmatch.demo`'s own docstring), so it never gets the "Scan job boards"
    button the tutorial's third step is about. This seeds a lone local-no-auth
    admin instead — the same account a plain `python3 app.py` creates for
    itself — with a small made-up profile and two applications, just enough
    for the skills picker and the tracker table to have something to show.
    """
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["DATABASE_URL"] = f"sqlite:///{data_dir / 'jobmatch.db'}"
    os.environ["DEMO_MODE"] = "false"

    if not synthetic:
        if not LIVE_DB.exists():
            raise SystemExit(f"no {LIVE_DB} to copy — pass --synthetic")
        copy_live_db(data_dir / "jobmatch.db")

    import config  # imported here: it reads the environment set above

    config.DATA_DIR = data_dir
    config.RESUME_DIR = data_dir / "resumes"
    config.DB_PATH = data_dir / "jobmatch.db"
    config.DEMO_MODE = False

    from jobmatch import db, scoring

    conn = db.get_conn()
    db.init_schema(conn)
    if synthetic:
        synthetic_jobs(conn)
    # The only user in an otherwise-empty `users` table, so `db.admin_user_id`
    # finds it immediately — exactly how a fresh local-no-auth box resolves
    # its first request, just done ahead of time so there is a user id to
    # seed the rest of this against before the server ever starts.
    user_id = db.ensure_local_user(conn)
    db.set_settings(conn, user_id, {
        "user_skills": ["python", "react", "docker", "sql"],
        "user_worktype": "remote",
    })
    db.ensure_user_jobs(conn, user_id)
    scoring.rescore_user(conn, user_id)
    top = conn.execute(
        """SELECT job_id FROM user_jobs
           WHERE user_id = :u AND match_score IS NOT NULL
           ORDER BY match_score DESC, job_id LIMIT 2""",
        {"u": user_id},
    ).fetchall()
    for i, row in enumerate(top):
        conn.execute(
            """INSERT INTO applications (user_id, job_id, applied_at, status)
               VALUES (:u, :j, date('now', :offset), :status)""",
            {"u": user_id, "j": row["job_id"], "offset": f"-{3 + i * 4} days",
             "status": "interview" if i == 0 else "applied"},
        )
        conn.execute(
            "UPDATE user_jobs SET status = 'applied' WHERE user_id = :u AND job_id = :j",
            {"u": user_id, "j": row["job_id"]},
        )
    conn.commit()
    conn.close()
    print(f"tutorial: seeded user {user_id}, {len(top)} applications")


def serve(data_dir, port, demo_mode=True, scan_enabled=False):
    """`python3 app.py` against the scratch copy — the real entrypoint.

    `scan_enabled` only widens `can_scan` (so the tutorial pass's admin user
    gets the "Scan job boards" button to photograph); `SCAN_IN_PROCESS` stays
    off regardless, and nothing in this script ever clicks that button, so no
    combination of these flags can make this process touch a real job board.
    """
    env = dict(
        os.environ,
        DATA_DIR=str(data_dir),
        DATABASE_URL=f"sqlite:///{data_dir / 'jobmatch.db'}",
        DEMO_MODE="true" if demo_mode else "false",
        SCAN_ENABLED="true" if scan_enabled else "false",
        SCAN_IN_PROCESS="false",
        PORT=str(port),
        HOST="127.0.0.1",
        LOG_LEVEL="WARNING",
    )
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=REPO, env=env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=1).read()
            return proc, base
        except (urllib.error.URLError, ConnectionError) as err:
            if proc.poll() is not None:
                raise SystemExit("the app exited before it served anything") from err
            time.sleep(0.2)
    proc.terminate()
    raise SystemExit("the app never came up")


def shoot(page, base, scheme, suffix):
    page.emulate_media(color_scheme=scheme)
    for name, path, action in PAGES:
        page.goto(base + path, wait_until="networkidle")
        # The lists arrive by fetch(); a skeleton row is not what to photograph.
        page.wait_for_timeout(700)
        if action == "open_breakdown":
            score = page.locator(".job .score").first
            if score.count():
                score.click()
                page.wait_for_timeout(250)
        out = OUT_DIR / f"{name}{suffix}.png"
        page.screenshot(path=str(out))
        print(f"  {out.relative_to(REPO)}")


NAV_HEIGHT = 60  # `nav { height: 60px; position: sticky; top: 0 }` in style.css


def clipped(locator, max_h, pad=8):
    """A bounding box around one element, capped tall so a long list doesn't
    turn a small tutorial image into a full scrolling page."""
    box = locator.bounding_box()
    if box is None:
        raise RuntimeError(f"{locator} is not visible — nothing to crop to")
    return {
        "x": max(box["x"] - pad, 0),
        "y": max(box["y"] - pad, 0),
        "width": box["width"] + pad * 2,
        "height": min(box["height"], max_h) + pad * 2,
    }


def shoot_tutorial(page, base, scheme, suffix):
    page.emulate_media(color_scheme=scheme)
    for name, path, selector, max_h in TUTORIAL_SHOTS:
        page.goto(base + path, wait_until="networkidle")
        page.wait_for_timeout(700)
        locator = page.locator(selector)
        # `scroll_into_view_if_needed` stops as soon as any part of the
        # element is on screen, which can leave its top edge sitting right
        # under the sticky nav rather than below it. Pin the element's top to
        # a fixed, known offset instead, so `bounding_box()` (read straight
        # after) and the eventual `clip` always agree on where it actually is.
        locator.evaluate(
            "(el, navH) => { el.scrollIntoView({block: 'start'}); "
            "window.scrollBy(0, -(navH + 16)); }",
            NAV_HEIGHT,
        )
        page.wait_for_timeout(200)
        out = TUTORIAL_DIR / f"{name}{suffix}.png"
        page.screenshot(path=str(out), clip=clipped(locator, max_h))
        print(f"  {out.relative_to(REPO)}")


def run_pass(prepare_fn, serve_fn, synthetic):
    """One prepare → serve → photograph → tear-down cycle, in its own scratch
    `DATA_DIR` and port — the demo pass and the tutorial pass each get a clean
    one, so neither's seed data or logged-in session leaks into the other's
    screenshots."""
    tmp = Path(tempfile.mkdtemp(prefix="jobmatch-shots-"))
    port = free_port()
    proc = None
    try:
        prepare_fn(tmp, synthetic)
        proc, base = serve_fn(tmp, port)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
            page = context.new_page()
            yield page, base
            browser.close()
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true",
                        help="invent a job pool instead of copying data/jobmatch.db")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TUTORIAL_DIR.mkdir(parents=True, exist_ok=True)

    print("demo account (landing page, README):")
    for page, base in run_pass(prepare, serve, args.synthetic):
        # One click, no password — the same button the landing page has.
        page.goto(base + "/", wait_until="networkidle")
        page.click("form[action='/demo'] button")
        page.wait_for_load_state("networkidle")
        for scheme, suffix in (("light", ""), ("dark", "-dark")):
            print(f"{scheme}:")
            shoot(page, base, scheme, suffix)

    print("tutorial modal (local-no-auth, its own seed):")
    for page, base in run_pass(
        prepare_tutorial,
        lambda d, p: serve(d, p, demo_mode=False, scan_enabled=True),
        args.synthetic,
    ):
        for scheme, suffix in (("light", ""), ("dark", "-dark")):
            print(f"{scheme}:")
            shoot_tutorial(page, base, scheme, suffix)


if __name__ == "__main__":
    main()

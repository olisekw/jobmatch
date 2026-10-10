"""Regenerate the screenshots the landing page and the README show.

    python3 tools/screenshots.py                 # from a copy of data/jobmatch.db
    python3 tools/screenshots.py --synthetic     # from made-up jobs, no real DB needed

Writes `static/screens/<page>.png` and `<page>-dark.png` — one pair per page, so
the landing page and GitHub can each pick the scheme the reader is already in.

Nothing here touches the real database. It is `.backup()`-copied into a scratch
`DATA_DIR`, the demo account is seeded *there*, and the app is started against
that copy as a subprocess — the same `python3 app.py` a developer runs, so what
gets photographed is the actual entrypoint and not a test client's idea of it.

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


def serve(data_dir, port):
    """`python3 app.py` against the scratch copy — the real entrypoint."""
    env = dict(
        os.environ,
        DATA_DIR=str(data_dir),
        DATABASE_URL=f"sqlite:///{data_dir / 'jobmatch.db'}",
        DEMO_MODE="true",
        # No scanning: this process must not touch a job board to take a photo.
        SCAN_ENABLED="false",
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true",
                        help="invent a job pool instead of copying data/jobmatch.db")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="jobmatch-shots-"))
    port = free_port()
    proc = None
    try:
        prepare(tmp, args.synthetic)
        proc, base = serve(tmp, port)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
            page = context.new_page()
            # One click, no password — the same button the landing page has.
            page.goto(base + "/", wait_until="networkidle")
            page.click("form[action='/demo'] button")
            page.wait_for_load_state("networkidle")
            for scheme, suffix in (("light", ""), ("dark", "-dark")):
                print(f"{scheme}:")
                shoot(page, base, scheme, suffix)
            browser.close()
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()

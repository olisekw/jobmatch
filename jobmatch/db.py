"""SQLite storage layer: connections, schema, and JSON-encoded settings."""

import json
import sqlite3

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY,
    source          TEXT NOT NULL DEFAULT 'profesia',
    source_id       TEXT NOT NULL,
    title           TEXT,
    company         TEXT,
    location        TEXT,
    salary          TEXT,
    freshness       TEXT,
    link            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    skills          TEXT NOT NULL DEFAULT '',
    worktype        TEXT,
    seniority       TEXT,
    employment_type TEXT,
    status          TEXT NOT NULL DEFAULT 'new'
                    CHECK (status IN ('new', 'applied', 'declined')),
    match_score     REAL,
    score_breakdown TEXT,
    scraped_at      TEXT NOT NULL DEFAULT (datetime('now')),
    scored_at       TEXT,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score  ON jobs(match_score);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);

CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY,
    job_id      INTEGER NOT NULL UNIQUE REFERENCES jobs(id),
    applied_at  TEXT NOT NULL DEFAULT (date('now')),
    status      TEXT NOT NULL DEFAULT 'applied'
                CHECK (status IN ('applied', 'interview', 'offer',
                                  'rejected', 'withdrawn', 'no_response')),
    notes       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS application_events (
    id             INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    event_at       TEXT NOT NULL DEFAULT (datetime('now')),
    from_status    TEXT,
    to_status      TEXT,
    note           TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scans (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'done', 'failed', 'cancelled')),
    found       INTEGER NOT NULL DEFAULT 0,
    enriched    INTEGER NOT NULL DEFAULT 0,
    matched     INTEGER NOT NULL DEFAULT 0,
    error       TEXT
);
"""

DEFAULT_SETTINGS = {
    "weight_skill": 0.4,
    "weight_worktype": 0.25,
    "weight_location": 0.2,
    "weight_seniority": 0.15,
    "min_match_score": 20,
    "seniority_strict": False,
    "search_terms": config.SEARCH_PROFILES[config.DEFAULT_SEARCH_PROFILE],
    "active_profile": config.DEFAULT_SEARCH_PROFILE,
    "enabled_sources": ["profesia", "kariera", "remoteok", "remotive", "jobicy", "arbeitnow"],
    "scan_days": 7,
    "user_location": "",
    "user_seniority": "",
    "user_worktype": "",
    "user_skills": [],
    "resume_text": "",
}


def get_conn(db_path=None):
    conn = sqlite3.connect(str(db_path or config.DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Columns added after the original release; applied idempotently to live DBs.
_JOBS_EXTRA_COLUMNS = {
    "posted_at": "TEXT",
    "salary_min": "REAL",
    "salary_max": "REAL",
    "salary_currency": "TEXT",
    "salary_period": "TEXT",
}


def init_schema(conn):
    conn.executescript(SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    for column, sqltype in _JOBS_EXTRA_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {sqltype}")
    conn.commit()


def get_setting(conn, key):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return DEFAULT_SETTINGS.get(key)
    return json.loads(row["value"])


def get_all_settings(conn):
    stored = {
        row["key"]: json.loads(row["value"])
        for row in conn.execute("SELECT key, value FROM settings")
    }
    merged = dict(DEFAULT_SETTINGS)
    merged.update(stored)
    return merged


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
    conn.commit()


def set_settings(conn, mapping):
    for key, value in mapping.items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
    conn.commit()


def get_weights(conn):
    s = get_all_settings(conn)
    return {
        "skills": float(s["weight_skill"]),
        "worktype": float(s["weight_worktype"]),
        "location": float(s["weight_location"]),
        "seniority": float(s["weight_seniority"]),
    }


def get_user_prefs(conn):
    s = get_all_settings(conn)
    return {
        "location": (s["user_location"] or "").strip().lower(),
        "seniority": (s["user_seniority"] or "").strip().lower(),
        "worktype": (s["user_worktype"] or "").strip().lower(),
        "skills": {str(x).strip().lower() for x in s["user_skills"] if str(x).strip()},
        "seniority_strict": bool(s["seniority_strict"]),
    }

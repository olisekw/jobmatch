"""Storage layer: SQLAlchemy Core engine, schema, and per-user JSON settings.

Two deliberate choices here:

- **Core, not the ORM.** The schema is declared as `Table` objects so DDL is
  dialect-correct and `create_all` is idempotent, but every *query* in the
  codebase stays plain `text()` SQL. The SQL was readable before multi-tenancy
  and it still is; an ORM would have bought nothing.
- **Named bind parameters (`:name`), never qmark.** `?` is a DBAPI paramstyle,
  not SQL — sqlite3 speaks it and psycopg2 does not. Named params are what
  makes the Phase 5 Postgres switch a URL change.

`Connection` below is a thin façade that keeps the reading shape the rest of
the code already uses: `conn.execute(sql, params)`, `row["column"]`, `dict(row)`.

The job pool in `jobs` is **global and shared** — one scrape serves every user.
Everything a user owns (status, score, settings, applications) hangs off
`user_id`; see ROADMAP.md for why the crawl must not multiply per user.
"""

import json

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.schema import CreateColumn

import config

metadata = MetaData()

# Timestamp defaults are SQLite-flavoured on purpose. The columns are TEXT and
# every reader (dates.days_ago, the JSON API, the templates) expects exactly the
# 'YYYY-MM-DD HH:MM:SS' string datetime('now') produces. Phase 5 swaps these for
# their Postgres equivalents along with the rest of the dialect gaps.
NOW = text("(datetime('now'))")
TODAY = text("(date('now'))")
EMPTY = text("''")

JOB_STATUSES = ("new", "applied", "declined")
APPLICATION_STATUSES = ("applied", "interview", "offer", "rejected", "withdrawn", "no_response")
SCAN_STATUSES = ("queued", "running", "done", "failed", "cancelled")


def _in_list(column, values):
    """A CHECK ... IN (...) clause written out, so the DDL still reads as SQL."""
    return "{} IN ({})".format(column, ", ".join(f"'{v}'" for v in values))


users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("email", Text, nullable=False),
    # Empty until Phase 3 wires up argon2 — the migrated local user has no
    # password yet, and an empty hash can never match a verify().
    Column("password_hash", Text, nullable=False, server_default=EMPTY),
    Column("created_at", Text, nullable=False, server_default=NOW),
    Column("is_admin", Integer, nullable=False, server_default=text("0")),
    UniqueConstraint("email", name="uq_users_email"),
)

# Global, shared, user-independent: what the boards told us plus what regex
# extraction derived. Nothing in here differs between two users.
jobs = Table(
    "jobs", metadata,
    Column("id", Integer, primary_key=True),
    Column("source", Text, nullable=False, server_default=text("'profesia'")),
    Column("source_id", Text, nullable=False),
    Column("title", Text),
    Column("company", Text),
    Column("location", Text),
    Column("salary", Text),
    Column("freshness", Text),
    Column("link", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=EMPTY),
    Column("skills", Text, nullable=False, server_default=EMPTY),
    Column("worktype", Text),
    Column("seniority", Text),
    Column("employment_type", Text),
    Column("scraped_at", Text, nullable=False, server_default=NOW),
    Column("posted_at", Text),
    Column("salary_min", Float),
    Column("salary_max", Float),
    Column("salary_currency", Text),
    Column("salary_period", Text),
    UniqueConstraint("source", "source_id", name="uq_jobs_source"),
)
Index("idx_jobs_source", jobs.c.source)
Index("idx_jobs_posted", jobs.c.posted_at)

# One row per (user, job): everything scoring and triage own.
user_jobs = Table(
    "user_jobs", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("job_id", Integer, ForeignKey("jobs.id"), nullable=False),
    Column("status", Text, nullable=False, server_default=text("'new'")),
    Column("match_score", Float),
    Column("score_breakdown", Text),
    Column("scored_at", Text),
    CheckConstraint(_in_list("status", JOB_STATUSES), name="ck_user_jobs_status"),
    UniqueConstraint("user_id", "job_id", name="uq_user_jobs_user_job"),
)
Index("idx_user_jobs_status", user_jobs.c.user_id, user_jobs.c.status)
Index("idx_user_jobs_score", user_jobs.c.user_id, user_jobs.c.match_score)

user_settings = Table(
    "user_settings", metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
)

applications = Table(
    "applications", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("job_id", Integer, ForeignKey("jobs.id"), nullable=False),
    Column("applied_at", Text, nullable=False, server_default=TODAY),
    Column("status", Text, nullable=False, server_default=text("'applied'")),
    Column("notes", Text, nullable=False, server_default=EMPTY),
    CheckConstraint(_in_list("status", APPLICATION_STATUSES), name="ck_applications_status"),
    # Was globally unique on job_id; two users applying to the same posting is
    # normal, so uniqueness is now per user.
    UniqueConstraint("user_id", "job_id", name="uq_applications_user_job"),
)

application_events = Table(
    "application_events", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("application_id", Integer, ForeignKey("applications.id"), nullable=False),
    Column("event_at", Text, nullable=False, server_default=NOW),
    Column("from_status", Text),
    Column("to_status", Text),
    Column("note", Text),
)
Index("idx_application_events_app", application_events.c.application_id)

scans = Table(
    "scans", metadata,
    Column("id", Integer, primary_key=True),
    Column("started_at", Text, nullable=False, server_default=NOW),
    Column("finished_at", Text),
    Column("status", Text, nullable=False, server_default=text("'running'")),
    Column("found", Integer, nullable=False, server_default=text("0")),
    Column("enriched", Integer, nullable=False, server_default=text("0")),
    Column("matched", Integer, nullable=False, server_default=text("0")),
    Column("error", Text),
    # `error` is a traceback and belongs in the log. This holds the same
    # failures keyed by source name as JSON, so the dashboard can say which
    # boards struggled without showing anybody a stack trace.
    Column("source_errors", Text),
    # Phase 4 turns this table into the queue; the columns land now so the
    # migration is not run twice against a live database.
    Column("trigger", Text, nullable=False, server_default=text("'manual'")),
    Column("requested_by", Integer, ForeignKey("users.id")),
    CheckConstraint(_in_list("status", SCAN_STATUSES), name="ck_scans_status"),
)

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

# Settings that belong to the shared crawl rather than to one user. They stay in
# the per-user table for now (the local user is the admin), but scanning reads
# them from the admin, not from whoever triggered it — see scan.scan_settings().
SCAN_SETTING_KEYS = ("search_terms", "enabled_sources", "scan_days", "active_profile")


# ── Engine / connection ──────────────────────────────────────

_ENGINES = {}


def _url(db_path=None):
    """Resolve the SQLAlchemy URL, honouring a test-patched `config.DB_PATH`."""
    if db_path is not None:
        return f"sqlite:///{db_path}"
    if config.DB_PATH is not None:
        return f"sqlite:///{config.DB_PATH}"
    return config.DATABASE_URL


def get_engine(db_path=None):
    """One engine per URL, created on first use and cached."""
    url = _url(db_path)
    engine = _ENGINES.get(url)
    if engine is not None:
        return engine

    if url.startswith(config.SQLITE_URL_PREFIX):
        path = config.sqlite_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)

    engine = sa.create_engine(url, future=True)
    if engine.dialect.name == "sqlite":
        @sa.event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _ENGINES[url] = engine
    return engine


class Result:
    """Cursor result whose rows are mappings, so `row["col"]` and `dict(row)` work."""

    def __init__(self, cursor_result):
        self._result = cursor_result
        self._mappings = None

    def _rows(self):
        if self._mappings is None:
            self._mappings = self._result.mappings()
        return self._mappings

    @property
    def rowcount(self):
        return self._result.rowcount

    def fetchone(self):
        return self._rows().fetchone()

    def fetchall(self):
        return self._rows().fetchall()

    def __iter__(self):
        return iter(self._rows())


class Connection:
    """Thin façade over a SQLAlchemy Core connection.

    Transactions are explicit, exactly as with sqlite3: a write is not durable
    until `commit()`. Closing without committing rolls back.
    """

    def __init__(self, engine):
        self.sa = engine.connect()
        self.dialect = engine.dialect.name

    def execute(self, sql, params=None):
        return Result(self.sa.execute(text(sql), params or {}))

    def executemany(self, sql, seq_of_params):
        """Run one statement over many parameter dicts. No-op on an empty sequence."""
        rows = list(seq_of_params)
        if not rows:
            return 0
        return self.sa.execute(text(sql), rows).rowcount

    def scalar(self, sql, params=None):
        """First column of the first row.

        Also how new ids are read back: `INSERT … RETURNING id`. cursor.lastrowid
        is a DBAPI detail that `text()` statements cannot reach and Postgres does
        not have; RETURNING is understood by both sqlite 3.35+ and Postgres.
        """
        return self.sa.execute(text(sql), params or {}).scalar()

    def commit(self):
        self.sa.commit()

    def rollback(self):
        self.sa.rollback()

    def close(self):
        self.sa.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def get_conn(db_path=None):
    return Connection(get_engine(db_path))


# ── Schema creation ──────────────────────────────────────────

def init_schema(conn):
    """Create missing tables and add missing *additive* columns. Idempotent.

    Columns that are NOT NULL without a server default cannot be bolted onto a
    populated table — those arrive with the one-time table rebuilds in
    `jobmatch.backfill`, which have the data to fill them.
    """
    metadata.create_all(conn.sa, checkfirst=True)
    conn.commit()

    inspector = sa.inspect(conn.sa)
    for table in metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            if not column.nullable and column.server_default is None:
                continue  # backfill's job — it knows what to put there
            conn.execute(
                f"ALTER TABLE {table.name} ADD COLUMN {_column_ddl(conn, column)}"
            )
    conn.commit()


def _column_ddl(conn, column):
    """DDL fragment for one column, rendered by the dialect that will run it."""
    return str(CreateColumn(column).compile(dialect=conn.sa.dialect))


# ── Users ────────────────────────────────────────────────────

def create_user(conn, email, password_hash="", is_admin=False):
    """Insert a user and return its id. Caller commits."""
    return conn.scalar(
        "INSERT INTO users (email, password_hash, is_admin) "
        "VALUES (:email, :password_hash, :is_admin) RETURNING id",
        {
            "email": (email or "").strip().lower(),
            "password_hash": password_hash,
            "is_admin": 1 if is_admin else 0,
        },
    )


def get_user(conn, user_id):
    return conn.execute(
        "SELECT id, email, created_at, is_admin FROM users WHERE id = :id", {"id": user_id}
    ).fetchone()


def get_user_by_email(conn, email):
    return conn.execute(
        "SELECT id, email, password_hash, created_at, is_admin FROM users "
        "WHERE email = :email",
        {"email": (email or "").strip().lower()},
    ).fetchone()


def default_user_id(conn):
    """The single local user, until Phase 3 puts a login in front of everything."""
    return conn.scalar("SELECT id FROM users ORDER BY id LIMIT 1")


def ensure_local_user(conn):
    """The user everything belongs to before Phase 3 puts a login in front.

    Returns the existing user on any populated database, so this is safe to run
    at every startup. The account is created with an empty password_hash — it
    cannot be logged into until Phase 3 sets one, which is the intent: it exists
    to own the local data, not to authenticate.
    """
    user_id = default_user_id(conn)
    if user_id is not None:
        return user_id
    user_id = create_user(conn, config.LOCAL_USER_EMAIL, is_admin=True)
    conn.commit()
    return user_id


def admin_user_id(conn):
    """Whose settings drive the shared crawl. Falls back to the first user."""
    return conn.scalar(
        "SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1"
    ) or default_user_id(conn)


def ensure_user_jobs(conn, user_id):
    """Materialize missing (user, job) rows. Returns how many were created.

    Called on signup and after every scan. One INSERT … SELECT rather than a
    row per job, so score filtering and sorting stay in SQL.
    """
    inserted = conn.execute(
        """INSERT INTO user_jobs (user_id, job_id)
           SELECT :user_id, j.id FROM jobs j
           WHERE NOT EXISTS (
               SELECT 1 FROM user_jobs uj
               WHERE uj.user_id = :user_id AND uj.job_id = j.id
           )""",
        {"user_id": user_id},
    ).rowcount
    conn.commit()
    return inserted


def delete_user(conn, user_id):
    """Wipe everything a user owns. Phase 3 exposes this as account deletion."""
    params = {"user_id": user_id}
    for sql in (
        "DELETE FROM application_events WHERE user_id = :user_id",
        "DELETE FROM applications WHERE user_id = :user_id",
        "DELETE FROM user_jobs WHERE user_id = :user_id",
        "DELETE FROM user_settings WHERE user_id = :user_id",
        "UPDATE scans SET requested_by = NULL WHERE requested_by = :user_id",
        "DELETE FROM users WHERE id = :user_id",
    ):
        conn.execute(sql, params)
    conn.commit()


# ── Settings (per user) ──────────────────────────────────────

def get_setting(conn, user_id, key):
    row = conn.execute(
        "SELECT value FROM user_settings WHERE user_id = :user_id AND key = :key",
        {"user_id": user_id, "key": key},
    ).fetchone()
    if row is None:
        return DEFAULT_SETTINGS.get(key)
    return json.loads(row["value"])


def get_all_settings(conn, user_id):
    stored = {
        row["key"]: json.loads(row["value"])
        for row in conn.execute(
            "SELECT key, value FROM user_settings WHERE user_id = :user_id",
            {"user_id": user_id},
        )
    }
    merged = dict(DEFAULT_SETTINGS)
    merged.update(stored)
    return merged


def set_settings(conn, user_id, mapping):
    conn.executemany(
        "INSERT INTO user_settings (user_id, key, value) "
        "VALUES (:user_id, :key, :value) "
        "ON CONFLICT (user_id, key) DO UPDATE SET value = excluded.value",
        [
            {"user_id": user_id, "key": key, "value": json.dumps(value)}
            for key, value in mapping.items()
        ],
    )
    conn.commit()


def set_setting(conn, user_id, key, value):
    set_settings(conn, user_id, {key: value})


def get_weights(conn, user_id):
    s = get_all_settings(conn, user_id)
    return {
        "skills": float(s["weight_skill"]),
        "worktype": float(s["weight_worktype"]),
        "location": float(s["weight_location"]),
        "seniority": float(s["weight_seniority"]),
    }


def get_user_prefs(conn, user_id):
    s = get_all_settings(conn, user_id)
    return {
        "location": (s["user_location"] or "").strip().lower(),
        "seniority": (s["user_seniority"] or "").strip().lower(),
        "worktype": (s["user_worktype"] or "").strip().lower(),
        "skills": {str(x).strip().lower() for x in s["user_skills"] if str(x).strip()},
        "seniority_strict": bool(s["seniority_strict"]),
    }

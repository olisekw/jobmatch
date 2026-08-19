"""Set a user's password from the command line.

    python3 -m jobmatch.setpassword                       # the existing local user
    python3 -m jobmatch.setpassword you@example.com       # that user, or a new admin
    python3 -m jobmatch.setpassword you@example.com --admin

Two jobs, both of which need to work without a browser:

- **Give the migrated account a password.** `local@jobmatch.local` owns every
  job, status and application on a database that predates auth, and it was
  created with an empty `password_hash` — which no argon2 `verify()` can ever
  satisfy. Until this runs, that account is inert by design.
- **Create the first admin on a fresh deployment**, where signing up through
  the form would be a race with whoever finds the URL first.

The password is read from a prompt (never echoed, never an argv the shell
history and `ps` can both see), or from `JOBMATCH_PASSWORD` for scripting.
"""

import getpass
import os
import sys

import config

from . import auth, db

PASSWORD_ENV = "JOBMATCH_PASSWORD"


def read_password():
    """From the environment if scripted, otherwise a confirmed prompt."""
    scripted = os.environ.get(PASSWORD_ENV)
    if scripted:
        return scripted
    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Repeat it: "):
        raise SystemExit("The two passwords differ — nothing was changed.")
    return password


def set_password(conn, email, password, make_admin=False):
    """Create or update one account. Returns (user_id, created)."""
    problem = auth.email_problem(email) or auth.password_problem(password)
    if problem:
        raise SystemExit(problem)

    row = db.get_user_by_email(conn, email)
    password_hash = auth.hash_password(password)
    if row is None:
        # A brand-new account with nothing in it is only useful as an admin if
        # there is no admin yet; otherwise --admin has to be asked for.
        first = db.default_user_id(conn) is None
        user_id = db.create_user(conn, email, password_hash, is_admin=first or make_admin)
        conn.commit()
        # Without this the new account's Jobs page is empty until the next scan.
        db.ensure_user_jobs(conn, user_id)
        return user_id, True

    db.set_password(conn, row["id"], password_hash)
    if make_admin:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = :id", {"id": row["id"]})
        conn.commit()
    return row["id"], False


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    make_admin = "--admin" in argv
    positional = [a for a in argv if not a.startswith("-")]
    email = positional[0] if positional else config.LOCAL_USER_EMAIL

    conn = db.get_conn()
    try:
        db.init_schema(conn)
        password = read_password()
        user_id, created = set_password(conn, email, password, make_admin)
        verb = "created" if created else "updated"
        admin = " (admin)" if db.get_user(conn, user_id)["is_admin"] else ""
        print(f"{verb} user {user_id}: {auth.normalize_email(email)}{admin}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

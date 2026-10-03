"""Passwords, credential rules, and the Flask-Login user object.

Kept free of Flask *routing* on purpose: `jobmatch.setpassword` needs the
hashing and the validation without importing the web app, and the tests can
check the rules without a request context.

Argon2id is the default of `argon2-cffi`, with its default parameters. They
are chosen by the library to be reasonable on current hardware and are encoded
into the hash itself, so raising them later is a `needs_rehash()` away rather
than a migration.
"""

import re

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError
from flask_login import UserMixin

import config

_hasher = PasswordHasher()

# Deliberately permissive: "something@something.something, no spaces". The only
# real proof an address exists is mail sent to it, and this app sends none — so
# a strict RFC 5322 regex would reject real addresses to buy nothing.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

EMAIL_MAX_LENGTH = 254        # the practical limit on an address
PASSWORD_MAX_LENGTH = 1024    # argon2 is not fast; don't hash a whole upload


def normalize_email(email):
    """Lowercased and stripped — the form every lookup and insert uses."""
    return (email or "").strip().lower()


def email_problem(email):
    """Why this address can't be used, or None if it can."""
    email = normalize_email(email)
    if not email:
        return "Enter your email address."
    if len(email) > EMAIL_MAX_LENGTH:
        return "That email address is too long."
    if not EMAIL_RE.match(email):
        return "That does not look like an email address."
    return None


def password_problem(password):
    """Why this password can't be used, or None if it can."""
    password = password or ""
    if not password:
        return "Enter a password."
    if len(password) < config.MIN_PASSWORD_LENGTH:
        return f"Use at least {config.MIN_PASSWORD_LENGTH} characters."
    if len(password) > PASSWORD_MAX_LENGTH:
        return "That password is too long."
    return None


def hash_password(password):
    return _hasher.hash(password)


def verify_password(password_hash, password):
    """True if the password matches. Never raises — a bad hash is a mismatch.

    The migrated local user carries an empty `password_hash` by design, and
    every other stored hash is opaque to this function; both must simply fail
    to verify rather than blowing up a login form.
    """
    if not password_hash or not password:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (Argon2Error, InvalidHashError, TypeError):
        return False


_DUMMY_HASH = None


def dummy_verify(password):
    """Burn the same time a real verify costs, for an email with no account.

    Without this, "no such user" returns in microseconds while a wrong password
    takes argon2's full work factor — which turns the login form into a way to
    enumerate who has an account here.
    """
    # Two threads can both find it None and both hash (the web tier is one
    # process with `--threads 8`). Deliberately unlocked: the loser's hash is
    # thrown away, both are valid argon2 hashes of the same string, and the
    # point of this function is to *spend* that time anyway. Locking would
    # serialize the one call whose whole purpose is to be slow.
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("no-account-at-this-address")
    verify_password(_DUMMY_HASH, password)


def needs_rehash(password_hash):
    """True when the stored hash predates the current argon2 parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (Argon2Error, InvalidHashError, TypeError):
        return False


class User(UserMixin):
    """Flask-Login's view of a `users` row. Read-only; the DB stays the truth."""

    def __init__(self, row):
        self.id = row["id"]
        self.email = row["email"]
        self.is_admin = bool(row["is_admin"])

    def get_id(self):
        return str(self.id)

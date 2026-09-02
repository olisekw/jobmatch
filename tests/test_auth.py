"""Tests for Phase 3: passwords, sessions, tenant isolation and CSRF.

The load-bearing check here is the Phase 3 verification checkpoint from
ROADMAP.md — "two users, two browsers: each sees only their own tracker, and
changing user A's weights doesn't move user B's scores". `TenantIsolationTests`
is that checkpoint written down, with two Flask test clients standing in for
the two browsers.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import io
import tempfile
import unittest
from pathlib import Path

import config

# The app module reads config at import time, so anything a test needs to be
# true of the *app* has to be set before it is imported.
config.RATELIMIT_ENABLED = False

import app as webapp  # noqa: E402
from jobmatch import auth, db  # noqa: E402

PASSWORD = "correct-horse-battery"
OTHER_PASSWORD = "a-different-long-one"

MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


class AuthTestCase(unittest.TestCase):
    """A throwaway DB, a throwaway DATA_DIR, and CSRF on unless a test says otherwise."""

    csrf = False

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig = (config.DB_PATH, config.RESUME_DIR, config.ALLOW_SIGNUP)
        config.DB_PATH = tmp / "test.db"
        config.RESUME_DIR = tmp / "resumes"
        config.ALLOW_SIGNUP = True

        webapp.app.config["TESTING"] = True
        webapp.app.config["WTF_CSRF_ENABLED"] = self.csrf
        self.conn = db.get_conn()
        db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        config.DB_PATH, config.RESUME_DIR, config.ALLOW_SIGNUP = self._orig
        self._tmp.cleanup()

    def make_user(self, email, password=PASSWORD, is_admin=False):
        user_id = db.create_user(self.conn, email, auth.hash_password(password), is_admin)
        self.conn.commit()
        db.ensure_user_jobs(self.conn, user_id)
        return user_id

    def add_job(self, title="Python developer", **cols):
        # `skills` is what scoring reads — extraction fills it at scan time, and
        # these rows never go through a scan.
        params = dict(
            {"source": "remoteok", "source_id": title, "link": f"http://x/{title}",
             "title": title, "description": "Python and React, práca z domu.",
             "skills": "python,react", "worktype": "remote"},
            **cols,
        )
        job_id = self.conn.scalar(
            "INSERT INTO jobs ({}) VALUES ({}) RETURNING id".format(
                ", ".join(params), ", ".join(f":{k}" for k in params)),
            params,
        )
        self.conn.commit()
        return job_id

    def client_for(self, email, password=PASSWORD):
        """A logged-in test client — one per 'browser' in an isolation test."""
        client = webapp.app.test_client()
        res = client.post("/login", data={"email": email, "password": password})
        self.assertEqual(res.status_code, 302, "login did not redirect — it failed")
        return client


# ── Password rules and hashing ───────────────────────────────

class PasswordTests(unittest.TestCase):
    def test_hash_verifies_and_is_salted(self):
        first, second = auth.hash_password(PASSWORD), auth.hash_password(PASSWORD)
        self.assertNotEqual(first, second, "same password hashed twice must differ")
        self.assertTrue(auth.verify_password(first, PASSWORD))
        self.assertTrue(auth.verify_password(second, PASSWORD))

    def test_wrong_password_does_not_verify(self):
        self.assertFalse(auth.verify_password(auth.hash_password(PASSWORD), "wrong"))

    def test_the_migrated_empty_hash_can_never_verify(self):
        # The Phase 2 local user carries password_hash = ''. Nothing may open it.
        for attempt in ("", " ", PASSWORD, "\x00"):
            self.assertFalse(auth.verify_password("", attempt))

    def test_a_garbage_hash_is_a_mismatch_not_a_crash(self):
        self.assertFalse(auth.verify_password("not-an-argon2-hash", PASSWORD))

    def test_short_password_is_rejected(self):
        self.assertIsNotNone(auth.password_problem("a" * (config.MIN_PASSWORD_LENGTH - 1)))
        self.assertIsNone(auth.password_problem("a" * config.MIN_PASSWORD_LENGTH))

    def test_email_rules(self):
        for bad in ("", "  ", "nope", "no@domain", "two @spaces.com", "a" * 250 + "@x.com"):
            self.assertIsNotNone(auth.email_problem(bad), bad)
        for good in ("a@b.co", "First.Last+tag@example.museum"):
            self.assertIsNone(auth.email_problem(good), good)

    def test_email_is_normalized(self):
        self.assertEqual(auth.normalize_email("  Me@Example.COM "), "me@example.com")


# ── Login, signup, logout ────────────────────────────────────

class LoginTests(AuthTestCase):
    def test_pages_redirect_to_login_when_signed_out(self):
        client = webapp.app.test_client()
        # `/` is deliberately not in this list — as of Phase 7 it is the public
        # landing page, which is the next test.
        for path in ("/jobs", "/tracker", "/settings"):
            res = client.get(path)
            self.assertEqual(res.status_code, 302, path)
            self.assertIn("/login", res.headers["Location"], path)

    def test_the_front_page_greets_a_stranger_instead_of_a_login_form(self):
        """`/` is the URL that gets shared — it has to say what this is."""
        client = webapp.app.test_client()
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("scored against your CV", body)
        # And signing in still lands on the dashboard behind the same URL.
        self.make_user("home@example.com")
        res = self.client_for("home@example.com").get("/")
        self.assertIn("Best matches right now", res.get_data(as_text=True))

    def test_api_answers_401_json_rather_than_redirecting(self):
        # A fetch() following a redirect to an HTML page would report the login
        # form as a parse error; the client needs a status it can act on.
        client = webapp.app.test_client()
        res = client.get("/api/jobs")
        self.assertEqual(res.status_code, 401)
        self.assertIn("error", res.get_json())

    def test_login_succeeds_and_the_session_sticks(self):
        self.make_user("me@example.com")
        client = self.client_for("me@example.com")
        self.assertEqual(client.get("/jobs").status_code, 200)

    def test_wrong_password_does_not_log_in(self):
        self.make_user("me@example.com")
        client = webapp.app.test_client()
        res = client.post("/login", data={"email": "me@example.com", "password": "nope"})
        self.assertEqual(res.status_code, 200)  # the form again, not a redirect
        self.assertEqual(client.get("/api/jobs").status_code, 401)

    def test_unknown_and_wrong_are_worded_identically(self):
        # Anything that tells the two apart turns the form into an account
        # enumerator. The pages differ only where they echo back what was typed
        # into the email field, so it is the error that has to match.
        self.make_user("me@example.com")

        def error_shown(email):
            client = webapp.app.test_client()
            page = client.post(
                "/login", data={"email": email, "password": "nope"}
            ).get_data(as_text=True)
            return page.split('class="form-error" role="alert">')[1].split("<")[0]

        self.assertEqual(error_shown("me@example.com"), error_shown("nobody@example.com"))

    def test_the_migrated_local_user_cannot_be_logged_into(self):
        # An account with an empty hash exists to own rows, not to authenticate.
        db.ensure_local_user(self.conn)
        client = webapp.app.test_client()
        for attempt in ("", "anything"):
            client.post("/login", data={"email": config.LOCAL_USER_EMAIL, "password": attempt})
            self.assertEqual(client.get("/api/jobs").status_code, 401)

    def test_logout_ends_the_session(self):
        self.make_user("me@example.com")
        client = self.client_for("me@example.com")
        self.assertEqual(client.post("/logout").status_code, 302)
        self.assertEqual(client.get("/api/jobs").status_code, 401)

    def test_next_only_follows_a_same_site_path(self):
        self.make_user("me@example.com")
        for hostile in ("//evil.example", "https://evil.example/x", "javascript:alert(1)"):
            client = webapp.app.test_client()
            res = client.post(
                "/login",
                data={"email": "me@example.com", "password": PASSWORD, "next": hostile},
            )
            self.assertEqual(res.headers["Location"], "/", hostile)

    def test_next_follows_a_real_path(self):
        self.make_user("me@example.com")
        client = webapp.app.test_client()
        res = client.post(
            "/login", data={"email": "me@example.com", "password": PASSWORD, "next": "/tracker"}
        )
        self.assertEqual(res.headers["Location"], "/tracker")

    def test_a_deleted_account_does_not_keep_its_session(self):
        user_id = self.make_user("me@example.com")
        client = self.client_for("me@example.com")
        db.delete_user(self.conn, user_id)
        self.assertEqual(client.get("/api/jobs").status_code, 401)


class SignupTests(AuthTestCase):
    def _signup(self, client, email, password=PASSWORD, confirm=None):
        return client.post("/signup", data={
            "email": email, "password": password,
            "confirm": password if confirm is None else confirm,
        })

    def test_signup_creates_an_account_and_logs_it_in(self):
        client = webapp.app.test_client()
        res = self._signup(client, "new@example.com")
        self.assertEqual(res.status_code, 302)
        self.assertIsNotNone(db.get_user_by_email(self.conn, "new@example.com"))
        self.assertEqual(client.get("/settings").status_code, 200)

    def test_the_first_account_is_the_admin_and_later_ones_are_not(self):
        self._signup(webapp.app.test_client(), "first@example.com")
        self._signup(webapp.app.test_client(), "second@example.com")
        self.assertTrue(db.get_user_by_email(self.conn, "first@example.com")["is_admin"])
        self.assertFalse(db.get_user_by_email(self.conn, "second@example.com")["is_admin"])

    def test_a_new_account_gets_the_shared_pool_materialized(self):
        self.add_job("job one")
        self.add_job("job two")
        self._signup(webapp.app.test_client(), "new@example.com")
        user_id = db.get_user_by_email(self.conn, "new@example.com")["id"]
        self.assertEqual(
            self.conn.scalar("SELECT COUNT(*) FROM user_jobs WHERE user_id = :u", {"u": user_id}),
            2,
        )

    def test_a_duplicate_email_is_refused(self):
        self.make_user("taken@example.com")
        self._signup(webapp.app.test_client(), "taken@example.com", "another-long-one")
        self.assertEqual(
            self.conn.scalar("SELECT COUNT(*) FROM users WHERE email = 'taken@example.com'"), 1
        )

    def test_mismatched_confirmation_creates_nothing(self):
        self._signup(webapp.app.test_client(), "new@example.com", PASSWORD, "something-else")
        self.assertIsNone(db.get_user_by_email(self.conn, "new@example.com"))

    def test_a_short_password_creates_nothing(self):
        self._signup(webapp.app.test_client(), "new@example.com", "short")
        self.assertIsNone(db.get_user_by_email(self.conn, "new@example.com"))

    def test_signup_can_be_closed_by_config(self):
        config.ALLOW_SIGNUP = False
        client = webapp.app.test_client()
        self.assertEqual(client.get("/signup").status_code, 403)
        self.assertEqual(self._signup(client, "new@example.com").status_code, 403)
        self.assertIsNone(db.get_user_by_email(self.conn, "new@example.com"))


# ── The Phase 3 checkpoint ───────────────────────────────────

class TenantIsolationTests(AuthTestCase):
    """Two users, two clients — the ROADMAP checkpoint for this phase."""

    def setUp(self):
        super().setUp()
        self.job_id = self.add_job("Python developer")
        self.a = self.make_user("a@example.com")
        self.b = self.make_user("b@example.com", OTHER_PASSWORD)
        self.client_a = self.client_for("a@example.com")
        self.client_b = self.client_for("b@example.com", OTHER_PASSWORD)

    def test_a_status_change_is_not_visible_to_the_other_user(self):
        self.client_a.post(f"/api/jobs/{self.job_id}/status", json={"status": "applied"})
        a_jobs = self.client_a.get("/api/jobs?status=applied").get_json()["jobs"]
        b_jobs = self.client_b.get("/api/jobs?status=applied").get_json()["jobs"]
        self.assertEqual(len(a_jobs), 1)
        self.assertEqual(b_jobs, [])
        # And B still sees it as new, in the pool they share.
        self.assertEqual(len(self.client_b.get("/api/jobs?status=new").get_json()["jobs"]), 1)

    def test_trackers_do_not_overlap(self):
        self.client_a.post(f"/api/jobs/{self.job_id}/status", json={"status": "applied"})
        self.assertEqual(self.client_a.get("/api/applications").get_json()["count"], 1)
        self.assertEqual(self.client_b.get("/api/applications").get_json()["count"], 0)

    def test_one_users_application_cannot_be_edited_by_another(self):
        self.client_a.post(f"/api/jobs/{self.job_id}/status", json={"status": "applied"})
        app_id = self.client_a.get("/api/applications").get_json()["applications"][0]["id"]
        res = self.client_b.patch(f"/api/applications/{app_id}", json={"status": "rejected"})
        self.assertEqual(res.status_code, 404, "another user's id must be invisible, not editable")
        self.assertEqual(
            self.conn.scalar("SELECT status FROM applications WHERE id = :id", {"id": app_id}),
            "applied",
        )

    def test_changing_one_users_weights_does_not_move_the_others_scores(self):
        # The other half of the checkpoint: settings are per user, and so is the
        # rescore a settings change triggers.
        self.client_a.put("/api/settings", json={"user_skills": ["python", "react"]})
        self.client_b.put("/api/settings", json={"user_skills": ["cobol"]})
        before_b = self.conn.scalar(
            "SELECT match_score FROM user_jobs WHERE user_id = :u", {"u": self.b})

        self.client_a.put("/api/settings", json={
            "weight_skill": 1, "weight_worktype": 0, "weight_location": 0, "weight_seniority": 0,
        })

        after_b = self.conn.scalar(
            "SELECT match_score FROM user_jobs WHERE user_id = :u", {"u": self.b})
        self.assertEqual(before_b, after_b, "user B's score moved when user A saved weights")
        self.assertNotEqual(
            self.conn.scalar("SELECT match_score FROM user_jobs WHERE user_id = :u", {"u": self.a}),
            after_b,
            "the two users should not have converged on the same score",
        )

    def test_settings_are_read_back_per_user(self):
        self.client_a.put("/api/settings", json={"user_location": "Košice"})
        self.assertEqual(self.client_a.get("/api/settings").get_json()["user_location"], "Košice")
        self.assertEqual(self.client_b.get("/api/settings").get_json()["user_location"], "")

    def test_stats_count_only_the_callers_slice(self):
        self.client_a.post(f"/api/jobs/{self.job_id}/status", json={"status": "declined"})
        stats_a = self.client_a.get("/api/stats").get_json()
        stats_b = self.client_b.get("/api/stats").get_json()
        self.assertEqual((stats_a["declined"], stats_a["new_jobs"]), (1, 0))
        self.assertEqual((stats_b["declined"], stats_b["new_jobs"]), (0, 1))
        # The pool itself is shared and both must agree about its size.
        self.assertEqual(stats_a["total_jobs"], stats_b["total_jobs"])


# ── CSRF ─────────────────────────────────────────────────────

class CsrfTests(AuthTestCase):
    csrf = True

    def test_a_json_post_without_a_token_is_refused(self):
        self.make_user("me@example.com")
        job_id = self.add_job()
        client = webapp.app.test_client()
        # Log in through the form the way the browser does, token and all.
        page = client.get("/login").get_data(as_text=True)
        token = page.split('name="csrf_token" value="')[1].split('"')[0]
        client.post("/login", data={
            "email": "me@example.com", "password": PASSWORD, "csrf_token": token,
        })
        self.assertEqual(client.get("/jobs").status_code, 200, "login itself should work")

        res = client.post(f"/api/jobs/{job_id}/status", json={"status": "applied"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.get_json())
        self.assertEqual(
            self.conn.scalar("SELECT status FROM user_jobs WHERE job_id = :j", {"j": job_id}),
            "new",
            "the write went through despite the missing token",
        )

    def test_the_same_post_succeeds_with_the_header(self):
        self.make_user("me@example.com")
        job_id = self.add_job()
        client = webapp.app.test_client()
        page = client.get("/login").get_data(as_text=True)
        token = page.split('name="csrf_token" value="')[1].split('"')[0]
        client.post("/login", data={
            "email": "me@example.com", "password": PASSWORD, "csrf_token": token,
        })
        # The token app.js reads out of the <meta> tag on every page.
        meta = client.get("/jobs").get_data(as_text=True)
        header_token = meta.split('name="csrf-token" content="')[1].split('"')[0]

        res = client.post(
            f"/api/jobs/{job_id}/status",
            json={"status": "applied"},
            headers={"X-CSRFToken": header_token},
        )
        self.assertEqual(res.status_code, 200)


# ── Uploads and account deletion ─────────────────────────────

class ResumeUploadTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.user_id = self.make_user("me@example.com")
        self.client = self.client_for("me@example.com")

    def _upload(self, content, filename="cv.pdf"):
        return self.client.post(
            "/api/resume",
            data={"resume": (io.BytesIO(content), filename)},
            content_type="multipart/form-data",
        )

    def test_a_renamed_non_pdf_is_refused_before_it_is_written(self):
        res = self._upload(b"MZ\x90\x00 this is a windows binary", "cv.pdf")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(config.resume_path(self.user_id).exists(),
                         "a rejected upload must not reach the disk")

    def test_a_non_pdf_suffix_is_refused(self):
        self.assertEqual(self._upload(MINIMAL_PDF, "cv.exe").status_code, 400)

    def test_a_real_pdf_gets_past_the_magic_byte_check(self):
        # pdfplumber may still reject this stub; what matters is that the
        # rejection is no longer the magic-byte one and the file was saved.
        res = self._upload(MINIMAL_PDF)
        self.assertNotIn("not a PDF", res.get_json().get("error", ""))
        self.assertTrue(config.resume_path(self.user_id).exists())


class AccountDeletionTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.job_id = self.add_job()
        self.user_id = self.make_user("me@example.com")
        self.other_id = self.make_user("other@example.com", OTHER_PASSWORD)
        self.client = self.client_for("me@example.com")
        self.client.post(f"/api/jobs/{self.job_id}/status", json={"status": "applied"})
        self.client.put("/api/settings", json={"user_location": "Košice"})
        self.cv = config.resume_path(self.user_id)
        self.cv.parent.mkdir(parents=True, exist_ok=True)
        self.cv.write_bytes(MINIMAL_PDF)

    def _owned_rows(self, user_id):
        return {
            table: self.conn.scalar(
                f"SELECT COUNT(*) FROM {table} WHERE user_id = :u", {"u": user_id})
            for table in ("user_jobs", "user_settings", "applications", "application_events")
        }

    def test_the_wrong_password_deletes_nothing(self):
        res = self.client.post("/api/account/delete", json={"password": "not-it"})
        self.assertEqual(res.status_code, 403)
        self.assertIsNotNone(db.get_user(self.conn, self.user_id))
        self.assertTrue(self.cv.exists())

    def test_deletion_wipes_the_cv_the_rows_and_the_session(self):
        res = self.client.post("/api/account/delete", json={"password": PASSWORD})
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(db.get_user(self.conn, self.user_id))
        self.assertFalse(self.cv.exists(), "a CV is personal data and has to go with the account")
        self.assertEqual(set(self._owned_rows(self.user_id).values()), {0})
        self.assertEqual(self.client.get("/api/jobs").status_code, 401)

    def test_deletion_leaves_the_shared_pool_and_the_other_user_alone(self):
        self.client.post("/api/account/delete", json={"password": PASSWORD})
        self.assertEqual(self.conn.scalar("SELECT COUNT(*) FROM jobs"), 1)
        self.assertIsNotNone(db.get_user(self.conn, self.other_id))
        self.assertEqual(self._owned_rows(self.other_id)["user_jobs"], 1)


# ── The setpassword CLI ──────────────────────────────────────

class SetPasswordTests(AuthTestCase):
    def test_it_gives_the_migrated_local_user_a_usable_password(self):
        from jobmatch import setpassword

        user_id = db.ensure_local_user(self.conn)
        self.assertFalse(auth.verify_password(
            db.get_user_by_email(self.conn, config.LOCAL_USER_EMAIL)["password_hash"], PASSWORD))

        changed, created = setpassword.set_password(
            self.conn, config.LOCAL_USER_EMAIL, PASSWORD)
        self.assertEqual((changed, created), (user_id, False))

        client = self.client_for(config.LOCAL_USER_EMAIL)
        self.assertEqual(client.get("/jobs").status_code, 200)

    def test_it_creates_a_first_admin_on_an_empty_database(self):
        from jobmatch import setpassword

        user_id, created = setpassword.set_password(self.conn, "boss@example.com", PASSWORD)
        self.assertTrue(created)
        self.assertTrue(db.get_user(self.conn, user_id)["is_admin"])

    def test_it_refuses_a_password_the_signup_form_would_refuse(self):
        from jobmatch import setpassword

        with self.assertRaises(SystemExit):
            setpassword.set_password(self.conn, "boss@example.com", "short")


if __name__ == "__main__":
    unittest.main()

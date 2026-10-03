"""What the rendered pages actually ship to the browser.

Almost every other test speaks to the JSON API, which is the right place for
behaviour. These are the few facts that live in the markup instead — the globals
and the generated controls the inline scripts bind to. Without them a template
loop can stop emitting a slider and no test notices, which is exactly how the
five score components came to be written out in three places and the landing
page came to describe four of them.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import json
import unittest

from jobmatch import display
from tests.test_auth import AuthTestCase


class ScoreComponentMarkupTests(AuthTestCase):
    """The component list reaches every page that draws a bar or a slider."""

    def setUp(self):
        super().setUp()
        self.make_user("me@example.com")
        self.client = self.client_for("me@example.com")

    def components_on(self, path):
        body = self.client.get(path).get_data(as_text=True)
        marker = "window.SCORE_COMPONENTS = "
        self.assertIn(marker, body, f"{path} did not ship the component list")
        payload = body.split(marker, 1)[1].split(";</script>", 1)[0]
        return json.loads(payload)

    def test_every_signed_in_page_carries_the_list(self):
        # The job detail page is the reason this is a template global rather than
        # a key on `/api/settings`: it draws the breakdown without ever asking
        # for settings, so a list behind that route would cost it a request.
        job_id = self.add_job("Python developer")
        for path in ("/", "/jobs", f"/jobs/{job_id}", "/tracker", "/settings"):
            with self.subTest(path=path):
                self.assertEqual(
                    self.components_on(path), display.score_components(),
                    "the page and the server disagree about the components",
                )

    def test_the_settings_page_renders_one_slider_per_component(self):
        body = self.client.get("/settings").get_data(as_text=True)
        for c in display.score_components():
            slider = c["weight_key"].replace("weight_", "w-")
            with self.subTest(component=c["key"]):
                # The id, not the label: the inline script binds on the id, and
                # `weight_skill` is the one that is not its component's name.
                self.assertIn(f'id="{slider}"', body)
                self.assertIn(f'id="{slider}-out"', body)
                self.assertIn(f">{c['label']}</span>", body)


class SettingsPayloadTests(AuthTestCase):
    """`/api/settings` is read by three pages, so what it carries matters."""

    def setUp(self):
        super().setUp()
        self.make_user("me@example.com")
        self.client = self.client_for("me@example.com")

    def test_the_cv_text_is_not_shipped_to_every_page(self):
        settings = self.client.get("/api/settings").get_json()
        self.assertNotIn(
            "resume_text", settings,
            "the whole CV was being sent to the Jobs and Tracker pages, which "
            "never render it — only whether one exists is needed",
        )
        self.assertIn("resume_present", settings)
        self.assertFalse(settings["resume_present"])

    def test_it_offers_every_ordering_the_server_can_run(self):
        options = self.client.get("/api/settings").get_json()["sort_options"]
        self.assertEqual(
            [o["value"] for o in options], list(display.JOB_SORT),
            "the Sort dropdown is built from this list",
        )
        self.assertTrue(all(o["label"] for o in options))


class LandingCopyTests(AuthTestCase):
    """The front page states a count that the registry can contradict.

    It said "six boards" for as long as there were seven, in three places, and
    nothing could notice — so the number is interpolated now and this is what
    keeps it that way.
    """

    def test_it_names_as_many_boards_as_are_registered(self):
        import app as webapp
        from jobmatch.sources import SOURCES

        # Signed out: `/` is the landing page to a stranger.
        body = webapp.app.test_client().get("/").get_data(as_text=True)
        self.assertIn(f"{len(SOURCES)} boards", body)
        self.assertNotIn("six boards", body)
        # The phrase `test_e2e` asserts on has to survive the rewording.
        self.assertIn("scored against your CV", body)


if __name__ == "__main__":
    unittest.main()

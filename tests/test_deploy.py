"""Tests for the deployment contract: docker-compose.yml and deploy.yml.

These files are never exercised by the suite that runs on every push — they are
exercised by a box, once, and a mistake in them is found at the worst moment.
So the two properties that were *measured* rather than assumed are asserted
here, because both are the kind of thing a later tidy-up silently undoes.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
DEPLOY = (ROOT / ".github/workflows/deploy.yml").read_text()
DEPLOY_YML = yaml.safe_load(DEPLOY)
DEPLOY_DOC = (ROOT / "DEPLOY.md").read_text()


def step(name):
    """The shell body of a named step in the deploy job."""
    for s in DEPLOY_YML["jobs"]["deploy"]["steps"]:
        if s.get("name") == name:
            return s["run"]
    raise AssertionError(f"deploy.yml has no step named {name!r}")


class WaitCanFailTests(unittest.TestCase):
    """`docker compose up --wait` is the deploy's only check on the containers.

    Measured on compose v2.39: a service with no healthcheck is reported
    "Healthy" and `--wait` exits 0 *while the container is crash-looping* — so
    a broken `worker` used to deploy green, and nothing downstream noticed,
    because the smoke test only ever touches `web` through `caddy`. Every
    service declaring one is what makes a broken container a red deploy.
    """

    def test_every_service_declares_a_healthcheck(self):
        missing = [
            name for name, svc in COMPOSE["services"].items()
            if not (svc.get("healthcheck") or {}).get("test")
        ]
        self.assertEqual(missing, [], f"--wait cannot fail for: {missing}")

    def test_no_service_disables_its_healthcheck(self):
        for name, svc in COMPOSE["services"].items():
            with self.subTest(service=name):
                self.assertNotEqual(
                    svc["healthcheck"].get("disable"), True,
                    f"{name} would be skipped by --wait",
                )

    def test_the_deploy_still_waits(self):
        # On the command, not merely somewhere in the step: the comment
        # above it says "--wait" too, and matching that made this guard
        # pass with the flag deleted.
        self.assertRegex(
            step("Pull, rebuild and restart"), r"docker compose up[^\n]*--wait",
        )


class ReleaseIsCheckedTests(unittest.TestCase):
    """The smoke test has to tell "this commit is live" from "something answers".

    A status code alone cannot: a parked page on the same hostname answers 200,
    which was measured going green. `/healthz` reports `config.RELEASE`, so the
    deploy passes the sha in and the smoke test reads it back.
    """

    def test_the_deploy_passes_the_sha_as_release(self):
        body = step("Pull, rebuild and restart")
        self.assertRegex(body, r'RELEASE="\$SHA"\s+docker compose up')

    def test_web_and_worker_receive_release(self):
        for name in ("web", "worker"):
            with self.subTest(service=name):
                self.assertIn("RELEASE", COMPOSE["services"][name]["environment"])

    def test_the_smoke_test_reads_healthz_back_and_compares_it(self):
        body = step("Smoke-test the public URL")
        self.assertIn("/healthz", body)
        self.assertIn("release", body)
        self.assertIn("SHA", DEPLOY_YML["jobs"]["deploy"]["steps"][-1]["env"])


class SecretsAreDocumentedTests(unittest.TestCase):
    """DEPLOY.md §6 is the list someone works through when arming the pipeline.

    A secret the workflow reads but the doc never names is one that gets left
    unset, and an unset secret is not a build failure — it is an empty string.
    """

    def test_every_secret_the_workflow_reads_is_in_deploy_md(self):
        used = sorted(set(re.findall(r"secrets\.([A-Z_]+)", DEPLOY)))
        self.assertTrue(used, "no secrets found — did the workflow change shape?")
        undocumented = [s for s in used if f"`{s}`" not in DEPLOY_DOC]
        self.assertEqual(undocumented, [], f"not in DEPLOY.md: {undocumented}")


if __name__ == "__main__":
    unittest.main()

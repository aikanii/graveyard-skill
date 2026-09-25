#!/usr/bin/env python3
"""Integration and regression tests for the project-graveyard scanner."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "graveyard.py"
EMAIL = "graveyard-tests@example.com"

SPEC = importlib.util.spec_from_file_location("graveyard", str(SCRIPT))
GRAVEYARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRAVEYARD)


def days_ago(days):
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT10:00:00")


def make_repo(root, name):
    path = Path(root) / name
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.email", EMAIL], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "graveyard tests"],
                   cwd=str(path), check=True)
    return path


def commit(path, date, message, files):
    for filename in files:
        target = path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write("%s\n" % message)
    subprocess.run(["git", "add", "-A"], cwd=str(path), check=True)
    env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "commit", "-qm", message], cwd=str(path), env=env,
                   check=True)


def run_scanner(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + [str(arg) for arg in args] + ["--me", EMAIL],
        capture_output=True,
        text=True,
        timeout=60,
    )


class ClassifierUnitTests(unittest.TestCase):
    def base_repo(self, **changes):
        repo = {
            "name": "subject",
            "first": 1_000_000,
            "last": 1_000_000 + 40 * 86400,
            "last_touched": "src/core.py",
            "config_ratio": 0.1,
            "commits": 4,
            "has_readme": False,
            "has_deploy": True,
            "has_tags": False,
            "has_tests": False,
            "messages": ["init", "feature", "fix", "polish"],
            "files": 10,
            "top_dirs": 2,
            "gaps": [10, 10, 10],
        }
        repo.update(changes)
        return repo

    def primary_cause(self, repo, others=None):
        return GRAVEYARD.autopsy(repo, [repo] + (others or []))[0][0]

    def test_every_classifier_boundary(self):
        cases = {
            "payments_wall": self.base_repo(last_touched="app/stripe_checkout.py"),
            "auth_wall": self.base_repo(last_touched="src/oauth/login.py"),
            "boilerplate_wall": self.base_repo(config_ratio=0.6, commits=5),
            "deploy_fear": self.base_repo(
                has_readme=True, has_deploy=False, commits=20, config_ratio=0.59
            ),
            "rewrite_spiral": self.base_repo(
                messages=["rewrite parser", "migrate to sqlite", "fix", "docs"]
            ),
            "scope_explosion": self.base_repo(files=100, has_deploy=False),
            "slow_fade": self.base_repo(gaps=[10, 10, 30]),
            "unknown": self.base_repo(gaps=[]),
        }
        for expected, repo in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(self.primary_cause(repo), expected)

    def test_same_day_shiny_object_evidence_is_truthful(self):
        subject = self.base_repo(gaps=[])
        killer = self.base_repo(name="killer", first=subject["last"],
                                last=subject["last"] + 1)
        finding = GRAVEYARD.autopsy(subject, [subject, killer])[0]
        self.assertEqual(finding[0], "shiny_object")
        self.assertIn("0 day(s) after", finding[1])

    def test_deploy_markers_work_in_nested_packages(self):
        files = ["packages/web/src.js", "packages/web/vercel.json"]
        self.assertTrue(GRAVEYARD.has_path_marker(files, "vercel.json"))
        workflows = ["tools/release/.github/workflows/publish.yml"]
        self.assertTrue(GRAVEYARD.has_path_marker(workflows, ".github/workflows"))


class GraveyardIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = Path(tempfile.mkdtemp(prefix="graveyard-tests-"))

        boiler = make_repo(cls.workspace, "boiler-death")
        commit(boiler, days_ago(132), "init", ["package.json", ".gitignore"])
        commit(boiler, days_ago(130), "eslint", [".eslintrc.json", ".prettierrc"])
        commit(boiler, days_ago(126), "webpack", ["webpack.config.js", "tsconfig.json"])
        commit(boiler, days_ago(123), "jest", ["jest.config.js", "Dockerfile"])
        commit(boiler, days_ago(120), "tailwind", ["tailwind.config.js", "postcss.config.js"])

        killer = make_repo(cls.workspace, "killer-app")
        commit(killer, days_ago(117), "init", ["README.md", "src/index.js"])
        commit(killer, days_ago(2), "still going", ["src/more.js"])

        almost = make_repo(cls.workspace, "almost-shipped")
        commit(almost, days_ago(126), "init", ["package.json", "README.md"])
        for index in range(1, 21):
            commit(almost, days_ago(125 - index), "core %d" % index,
                   ["src/core%d.js" % index])
        commit(almost, days_ago(70), "polish", ["README.md", "tests/core.test.js"])

        payment = make_repo(cls.workspace, "pay-wall")
        commit(payment, days_ago(116), "init", ["main.py", "README.md"])
        commit(payment, days_ago(110), "logic", ["app/logic.py"])
        commit(payment, days_ago(105), "users", ["app/users.py"])
        commit(payment, days_ago(91), "stripe", ["app/stripe_checkout.py"])
        commit(payment, days_ago(90), "billing", ["app/billing.py"])

        shipped = make_repo(cls.workspace, "shipped-tool")
        # A nested deploy marker covers monorepos as well as root-level apps.
        commit(shipped, days_ago(150), "ship", [
            "README.md", "packages/web/vercel.json", "packages/web/src.js"
        ])
        subprocess.run([
            "git", "remote", "add", "origin",
            "https://example.com/private/shipped-tool.git",
        ], cwd=str(shipped), check=True)

        never_born = cls.workspace / "never-born"
        never_born.mkdir()
        (never_born / "package.json").write_text("{}\n", encoding="utf-8")
        (never_born / "app.js").write_text("// plans\n", encoding="utf-8")

        empty = cls.workspace / "empty-repo"
        empty.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(empty), check=True)

        foreign = make_repo(cls.workspace, "foreign-clone")
        subprocess.run(["git", "config", "user.email", "somebody-else@example.com"],
                       cwd=str(foreign), check=True)
        commit(foreign, days_ago(80), "upstream work", ["README.md", "library.py"])
        # Current local identity is ours, but none of the history is. This is a
        # realistic cloned checkout and must be filtered by author email.
        subprocess.run(["git", "config", "user.email", EMAIL], cwd=str(foreign),
                       check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.workspace), ignore_errors=True)

    def test_classification_and_evidence(self):
        result = run_scanner(self.workspace, "--days", "45", "--no-art")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout
        self.assertIn("alive: 1   finished: 1   dead: 3", output)
        self.assertIn("not yours (skipped): 1", output)
        self.assertIn("skipped as not-yours (by commit email): foreign-clone", output)
        self.assertIn("empty repositories (no commits): empty-repo", output)
        self.assertIn("unversioned", output)
        self.assertIn("never-born", output)
        self.assertIn("almost-shipped", output)
        self.assertIn("deploy fear", output)
        self.assertIn("payments wall", output)
        self.assertIn("killed by `killer-app`", output)
        dead_section = output.split("THE DEAD", 1)[1]
        self.assertNotIn("shipped-tool", dead_section)

    def test_include_foreign_is_explicit(self):
        result = run_scanner(self.workspace, "--days", "45", "--no-art",
                             "--include-foreign")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("alive: 1   finished: 1   dead: 4", result.stdout)
        self.assertIn("foreign-clone", result.stdout)
        self.assertIn("not yours (skipped): 0", result.stdout)

    def test_json_report_has_a_stable_complete_shape(self):
        report_path = self.workspace / "report.json"
        result = run_scanner(self.workspace, "--days", "45", "--no-art",
                             "--json", report_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["census"]["dead"], 3)
        self.assertEqual(report["census"]["empty"], 1)
        self.assertEqual(report["census"]["foreign_skipped"], 1)
        self.assertEqual(report["skipped"][0]["name"], "foreign-clone")
        self.assertEqual(len(report["finished"]), 1)
        self.assertEqual(len(report["unversioned"]), 1)
        self.assertTrue(all("causes" in item and "pulse" in item
                            for item in report["dead"]))
        self.assertTrue(all("messages" not in item and "last_touched" not in item
                            for item in report["dead"]))

    def test_redaction_masks_names_paths_remotes_and_relapse_output(self):
        state_path = self.workspace / "private-state.json"
        first = run_scanner(self.workspace, "--days", "45", "--no-art",
                            "--state", state_path)
        self.assertEqual(first.returncode, 0, first.stderr)
        marked = run_scanner("--state", state_path, "--mark-resurrected",
                             self.workspace / "almost-shipped")
        self.assertEqual(marked.returncode, 0, marked.stderr)

        report_path = self.workspace / "redacted.json"
        result = run_scanner(self.workspace, "--days", "45", "--no-art", "--redact",
                             "--state", state_path, "--json", report_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("almost-shipped", result.stdout)
        self.assertNotIn("killer-app", result.stdout)
        self.assertNotIn("foreign-clone", result.stdout)
        report_text = report_path.read_text(encoding="utf-8")
        self.assertNotIn("almost-shipped", report_text)
        self.assertNotIn("shipped-tool", report_text)
        self.assertNotIn("example.com/private", report_text)
        self.assertIn("project-", report_text)
        # State is deliberately private and must retain paths for future scans.
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertTrue(any(item["name"] == "almost-shipped"
                            for item in state["last_scan"]["dead"]))

    def test_state_relapse_and_malformed_state_recovery(self):
        state_path = self.workspace / "relapse-state.json"
        state_path.write_text("[]", encoding="utf-8")
        recovered = run_scanner(self.workspace, "--days", "45", "--no-art",
                                "--state", state_path)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("could not read state file", recovered.stderr)

        marked = run_scanner("--state", state_path, "--mark-resurrected",
                             self.workspace / "almost-shipped" / "src")
        self.assertEqual(marked.returncode, 0, marked.stderr)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(Path(state["resurrections"][0]["path"]),
                         (self.workspace / "almost-shipped").resolve())
        state["resurrections"][0]["date"] = days_ago(30).split("T", 1)[0]
        state_path.write_text(json.dumps(state), encoding="utf-8")

        result = run_scanner(self.workspace, "--days", "45", "--no-art",
                             "--state", state_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RELAPSE WATCH", result.stdout)
        self.assertIn("dying again", result.stdout)

    def test_no_dead_projects_still_write_json_and_state(self):
        root = Path(tempfile.mkdtemp(prefix="graveyard-alive-"))
        try:
            active = make_repo(root, "active")
            commit(active, days_ago(1), "active", ["README.md", "app.py"])
            report_path = root / "out" / "report.json"
            state_path = root / "out" / "state.json"
            result = run_scanner(root, "--days", "45", "--no-art",
                                 "--json", report_path, "--state", state_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(report["census"]["alive"], 1)
            self.assertEqual(report["dead"], [])
            self.assertEqual(len(state["last_scan"]["alive"]), 1)
        finally:
            shutil.rmtree(str(root), ignore_errors=True)

    def test_explicit_unversioned_root_is_reported(self):
        root = Path(tempfile.mkdtemp(prefix="graveyard-unversioned-"))
        try:
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n",
                                                 encoding="utf-8")
            report_path = root.parent / (root.name + "-report.json")
            result = run_scanner(root, "--no-art", "--json", report_path)
            self.assertEqual(result.returncode, 1)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["census"]["unversioned"], 1)
            self.assertEqual(report["unversioned"][0]["path"], str(root.resolve()))
            report_path.unlink()
        finally:
            shutil.rmtree(str(root), ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

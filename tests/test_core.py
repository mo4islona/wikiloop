"""Config validation, guide overrides, and the build/lint/check/init cycle on real directories."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import CLI, EXAMPLE, REPO
from wikiloop.candidate import missing_lines
from wikiloop.config import ConfigError, load
from wikiloop.render import Guides, RenderError, render_text, section_hash
from wikiloop.shepherd import pr_action

MINIMAL = """\
[wiki]
plugin = "test-wiki"
company = "Test"
domain = "Test systems"
repo = "test/wiki"
"""


def wiki(toml: str, guides: dict[str, str] | None = None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="wikiloop-wiki-"))
    (root / "wikiloop.toml").write_text(toml)
    (root / "skills").mkdir()
    for name, text in (guides or {}).items():
        (root / "guides").mkdir(exist_ok=True)
        (root / "guides" / f"{name}.md").write_text(text)
    return root


class ConfigTests(unittest.TestCase):
    def errors(self, extra: str) -> str:
        with self.assertRaises(ConfigError) as caught:
            load(wiki(MINIMAL + extra))
        return str(caught.exception)

    def test_minimal_config_loads_with_defaults(self):
        cfg = load(wiki(MINIMAL))
        self.assertEqual(cfg["inbox"]["repo"], "test/wiki")
        self.assertEqual(cfg["investigation"]["threshold"], 5)
        self.assertEqual(cfg["gate"]["keys"], "Why the wiki / Not repo or vendor")

    def test_rails_cannot_be_switched_off(self):
        self.assertIn("threshold", self.errors("[investigation]\nthreshold = 0\n"))
        self.assertIn("reask", self.errors("[investigation]\nreask = 1\n"))
        self.assertIn("names no signal", self.errors(
            "[investigation]\ndebug_skills = []\ncommands = []\nmcp_tools = []\n"))
        self.assertIn("gate.required", self.errors("[gate]\nrequired = []\n"))

    def test_typos_are_refused(self):
        self.assertIn("unknown key `investigation.treshold`", self.errors("[investigation]\ntreshold = 3\n"))
        self.assertIn("unknown key `wiki.colour`", self.errors("colour = 1\n"))

    def test_report_bucket_is_required(self):
        self.assertIn("report_session.bucket", self.errors('[report_session]\nkind = "gcs"\n'))


class GuideTests(unittest.TestCase):
    def core_hash(self, name: str, section: str) -> str:
        return section_hash(dict(Guides(wiki(MINIMAL)).sections(name))[section])

    def test_replace_with_current_base_is_quiet(self):
        base = self.core_hash("contribute", "language")
        root = wiki(MINIMAL, {"contribute": f"<!-- section: language base={base} -->\nOur words.\n"})
        guides = Guides(root)
        self.assertEqual(guides.text("contribute", "language"), "Our words.")
        self.assertEqual(guides.warnings, [])

    def test_stale_base_warns_with_the_core_text(self):
        root = wiki(MINIMAL, {"contribute": "<!-- section: language base=00000000 -->\nOur words.\n"})
        guides = Guides(root)
        guides.text("contribute")
        self.assertEqual(len(guides.warnings), 1)
        self.assertIn("Write in English only", guides.warnings[0])

    def test_add_after_and_append(self):
        base = self.core_hash("contribute", "freshness")
        root = wiki(MINIMAL, {"contribute": (
            "<!-- section: secrets mode=add after=links -->\nOur secrets rule.\n"
            f"<!-- section: freshness mode=append base={base} -->\nAnd ask the owner.\n")})
        guides = Guides(root)
        ids = [sid for sid, _ in guides.sections("contribute")]
        self.assertEqual(ids[ids.index("links") + 1], "secrets")
        self.assertTrue(guides.text("contribute", "freshness").endswith("And ask the owner."))

    def test_override_of_a_missing_section_fails(self):
        root = wiki(MINIMAL, {"contribute": "<!-- section: gotchas -->\nx\n"})
        with self.assertRaises(RenderError):
            Guides(root).text("contribute")

    def test_variables_and_includes_render(self):
        cfg = load(wiki(MINIMAL))
        text = render_text("{{wiki.plugin}} / {{guide:hooks#gate-reason}}", cfg, Guides(wiki(MINIMAL)))
        self.assertTrue(text.startswith("test-wiki / test-wiki: this candidate lacks {missing}"))
        with self.assertRaises(RenderError):
            render_text("{{wiki.nothing}}", cfg)


class CandidateTests(unittest.TestCase):
    def test_gate_lines_must_be_lines(self):
        cfg = load(wiki(MINIMAL))
        self.assertEqual(missing_lines("Why the wiki: w\nNot repo or vendor: n", cfg), [])
        self.assertEqual(missing_lines("**Why the wiki:** w", cfg), ["Not repo or vendor"])
        self.assertEqual(len(missing_lines("I did not ask why the wiki matters", cfg)), 2)


class ShepherdTests(unittest.TestCase):
    def pr(self, comments: list[str], labels=(), checks="SUCCESS", head="abc1234def") -> dict:
        rollup = [{"status": "COMPLETED", "conclusion": checks}]
        return {"labels": [{"name": l} for l in labels], "comments": [{"body": c} for c in comments],
                "headRefOid": head, "mergeable": "MERGEABLE", "statusCheckRollup": rollup}

    def mark(self, verdict: str, rnd: int = 1, sha: str = "abc1234") -> str:
        return f"<!-- shepherd round={rnd} verdict={verdict} sha={sha} -->"

    def test_actions(self):
        self.assertEqual(pr_action(self.pr([]), 2)[0], "review")
        self.assertEqual(pr_action(self.pr([self.mark("merge")]), 2)[0], "merge")
        self.assertEqual(pr_action(self.pr([self.mark("merge")], checks="FAILURE"), 2)[0], "escalate")
        self.assertEqual(pr_action(self.pr([self.mark("fix")]), 2)[0], "apply")
        self.assertEqual(pr_action(self.pr([self.mark("block")], labels=["needs-human"]), 2)[0], "wait-human")

        two_rounds = [self.mark("fix", 1, "1111111"), self.mark("fix", 2, "2222222")]
        self.assertEqual(pr_action(self.pr(two_rounds), 2)[0], "escalate")


class CycleTests(unittest.TestCase):
    """The commands a wiki's CI runs, on the example and on a wiki fresh from `init`."""

    def cli(self, cwd: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(CLI), *args], cwd=cwd, capture_output=True, text=True)

    def test_example_is_up_to_date_and_clean(self):
        for args in (("build", "--check", "--strict"), ("lint", "--stale"), ("check",)):
            proc = self.cli(EXAMPLE, *args)
            self.assertEqual(proc.returncode, 0, f"wikiloop {' '.join(args)}:\n{proc.stdout}{proc.stderr}")

    def test_init_builds_a_wiki_that_passes_its_own_ci(self):
        target = Path(tempfile.mkdtemp(prefix="wikiloop-init-")) / "beta-wiki"
        try:
            proc = self.cli(REPO, "init", str(target), "--plugin", "beta-wiki", "--company", "Beta",
                            "--domain", "Beta systems", "--repo", "beta/wiki")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue((target / "core" / ".wikiloop-core.json").is_file())

            for args in (("build", "--check"), ("lint",), ("check",)):
                proc = subprocess.run([sys.executable, "core/bin/wikiloop", *args], cwd=target,
                                      capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, f"wikiloop {' '.join(args)}:\n{proc.stdout}{proc.stderr}")

            (target / "core" / "VERSION").write_text("9.9.9\n2030-01-01\n")
            proc = subprocess.run([sys.executable, "core/bin/wikiloop", "check"], cwd=target,
                                  capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0, "a hand-edited core must fail the check")
        finally:
            shutil.rmtree(target.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

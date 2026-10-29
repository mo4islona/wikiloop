"""`[oncall]` validation: a wiki tunes the watch, it cannot switch the rails off."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import ROOT, config  # noqa: E402

from oncall import defaults  # noqa: E402
from wikiloop import config as wiki_config  # noqa: E402

WIKI = """
[wiki]
plugin = "acme-wiki"
domain = "ACME systems"
company = "ACME"
repo = "acme/wiki"
"""


def errors(**oncall) -> list:
    return defaults.validate(config(**oncall))


class ValidateTests(unittest.TestCase):
    def test_the_fixture_is_valid(self):
        self.assertEqual(errors(), [])

    def test_resolve_after_cannot_be_switched_off(self):
        self.assertTrue(any("resolve_after" in e for e in errors(resolve_after=0)))

    def test_unknown_keys_are_named(self):
        found = errors(colour="red", subject={"lables": ["x"]}, sections=[{"title": "x", "styl": "full"}])

        self.assertIn("unknown key `oncall.colour`", found)
        self.assertIn("unknown key `oncall.subject.lables`", found)
        self.assertIn("unknown key `oncall.sections[0].styl`", found)

    def test_the_floor_cannot_sit_above_loud(self):
        self.assertTrue(any("floor" in e for e in errors(floor="critical")))

    def test_a_probe_needs_prometheus_and_known_tiers(self):
        probe = {"name": "lag", "query": "up == 0", "component": "x", "severity": {"default": "minor", "gold": "major"}}

        found = errors(probes=[probe])

        self.assertTrue(any("prometheus.url" in e for e in found))
        self.assertTrue(any("'gold'" in e for e in found))

    def test_a_severity_table_needs_a_default(self):
        found = errors(restarts={"enabled": True, "severity": {"crash-loop": {"core": "major"}}},
                       prometheus={"url": "https://prometheus.acme.example/api/v1/query"})

        self.assertTrue(any("restarts.severity.crash-loop" in e for e in found))

    def test_sections_are_checked(self):
        found = errors(sections=[{"title": "Odd", "style": "table", "min_severity": "p1"}])

        self.assertTrue(any("style" in e for e in found))
        self.assertTrue(any("'p1'" in e for e in found))

    def test_a_watch_needs_a_source(self):
        self.assertTrue(any("no source" in e for e in errors(alertmanager={"url": ""})))

    def test_the_state_dir_is_one_place(self):
        self.assertTrue(any("state_dir" in e for e in errors(state_dir="cache/oncall")))


class LoadTests(unittest.TestCase):
    def test_the_example_section_loads_through_the_wiki_config(self):
        example = (ROOT / "oncall" / "example.toml").read_text()

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "wikiloop.toml").write_text(WIKI + example)
            cfg = wiki_config.load(Path(tmp))

        oncall = cfg["oncall"]
        self.assertTrue(oncall["enabled"])
        self.assertEqual(oncall["probes"][0]["name"], "queue-stalled")
        self.assertEqual(oncall["thresholds"]["fleet_min"], 5)
        self.assertEqual(oncall["restarts"]["severity"]["restarted"], "info")


if __name__ == "__main__":
    unittest.main()

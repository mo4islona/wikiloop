"""The on-call screen in a real plugin host: generate a plugin with the default sections, then
`claude plugin validate` and `claude plugin test` it.

Needs the `claude` CLI, so it runs only with WIKILOOP_MOD_TESTS=1:

    WIKILOOP_MOD_TESTS=1 python3 -m unittest discover -s tests/oncall -p test_mod.py
    python3 tests/oncall/test_mod.py --write <folder>     # the plugin alone, to run claude by hand
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import ROOT, config  # noqa: E402

from oncall import build  # noqa: E402


def write_plugin(target: Path) -> Path:
    cfg = config()
    plugin = cfg["wiki"]["plugin"]

    for path, text in build.generate(cfg, target).items():
        if path.startswith("hooks/"):
            (target / path).parent.mkdir(parents=True, exist_ok=True)
            (target / path).write_text(text)

    tests = build.templated((ROOT / "oncall" / "mod" / "oncall.test.ts").read_text(), cfg)
    (target / "hooks" / "oncall" / "oncall.test.ts").write_text(tests)

    manifest = {"name": plugin, "version": "0.0.0", "description": "on-call screen under test", "types": build.TYPES}
    (target / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (target / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2))
    (target / "hooks" / "hooks.json").write_text(json.dumps({"modules": [build.MODULE]}, indent=2))
    return target


@unittest.skipUnless(os.environ.get("WIKILOOP_MOD_TESTS") == "1" and shutil.which("claude"),
                     "set WIKILOOP_MOD_TESTS=1 with the claude CLI installed")
class ModTests(unittest.TestCase):
    def claude(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["claude", "plugin", *args], capture_output=True, text=True, timeout=600)

    def test_the_generated_mod_validates_and_its_tests_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = write_plugin(Path(tmp) / "acme-wiki")

            validated = self.claude("validate", str(plugin))
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

            tested = self.claude("test", str(plugin))
            self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--write"]:
        print(write_plugin(Path(sys.argv[2]).resolve()))
    else:
        unittest.main()

"""`wikiloop candidate` against a fake gh: a tracker out of reach, the queue, and `send`."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import CLI, HOOKS, resolved_config
from wikiloop.candidate import queued

BODY = "Symptom: s\nRoot cause: r\nLesson: l\nWhy the wiki: w\nNot repo or vendor: n\n"

FAKE_GH = r'''
import json, os, sys
with open(os.environ["TEST_CALLS"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
if os.environ.get("TEST_OFFLINE"):
    sys.exit("error connecting to api.github.com")
if sys.argv[1:3] == ["issue", "list"]:
    print("[]")
else:
    print("https://github.com/acme/ai-wiki/issues/7")
'''


class QueueTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="wikiloop-candidate-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.config = resolved_config()
        self.queue = self.root / "cache" / "acme-wiki" / "candidates.md"
        self.calls = self.root / "calls"

        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(f"#!{sys.executable}\n" + FAKE_GH)
        gh.chmod(0o755)

        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "TEST_CALLS": str(self.calls),
                    "XDG_CACHE_HOME": str(self.root / "cache")}
        self.env.pop("CLAUDE_PLUGIN_ROOT", None)

    def candidate(self, *args: str, body: str = "", offline: bool = False) -> subprocess.CompletedProcess:
        env = {**self.env, **({"TEST_OFFLINE": "1"} if offline else {})}
        return subprocess.run([sys.executable, str(CLI), "candidate", "--config", str(self.config), *args],
                              input=body, capture_output=True, text=True, env=env)

    def gh_calls(self) -> list[list[str]]:
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def session_rule(self, config: Path | None = None) -> str:
        proc = subprocess.run([sys.executable, str(HOOKS / "session_start.py"), str(config or self.config)],
                              input=json.dumps({"session_id": "q1"}), capture_output=True, text=True, env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_search_without_the_tracker_reports_instead_of_crashing(self):
        proc = self.candidate("search", "pool", offline=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("NOT SEARCHED (error connecting to api.github.com)", proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_queued_candidates_are_sent_once_the_tracker_is_reachable(self):
        filed = self.candidate("file", "-t", "dispatch-api crash-loops", body=BODY, offline=True)
        commented = self.candidate("comment", "12", body="Also seen on stage.\n", offline=True)
        self.assertIn("NOT FILED", filed.stdout)
        self.assertIn("candidate send", filed.stdout)
        self.assertIn("NOT SENT", commented.stdout)
        self.assertIn("2 candidate(s) never reached the tracker", self.session_rule())

        self.calls.unlink()
        sent = self.candidate("send")
        self.assertEqual(sent.returncode, 0, sent.stdout + sent.stderr)
        actions = [call[:2] for call in self.gh_calls()]
        self.assertEqual(actions, [["issue", "create"], ["issue", "comment"]])
        self.assertEqual(self.gh_calls()[1][2], "12")

        self.assertEqual(self.queue.read_text(), "")
        self.assertNotIn("never reached the tracker", self.session_rule())
        self.assertIn("nothing queued", self.candidate("send").stdout)

    def test_a_config_from_an_older_core_still_gets_the_rules(self):
        self.candidate("file", "-t", "first", body=BODY, offline=True)
        cfg = json.loads(self.config.read_text())
        del cfg["texts"]["session_queued"]
        old = self.root / "old.json"
        old.write_text(json.dumps(cfg))

        rule = self.session_rule(old)
        self.assertIn("acme-wiki:wiki-contribute", rule)
        self.assertNotIn("never reached the tracker", rule)

    def test_send_without_the_tracker_keeps_the_queue(self):
        self.candidate("file", "-t", "first", body=BODY, offline=True)
        self.candidate("file", "-t", "second", body=BODY, offline=True)
        before = self.queue.read_text()

        proc = self.candidate("send", offline=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("2 of 2 still queued", proc.stdout)
        self.assertEqual(self.queue.read_text(), before)

    def test_a_note_above_the_queue_survives_a_send(self):
        self.queue.parent.mkdir(parents=True)
        self.queue.write_text("my note\n")
        self.candidate("file", "-t", "first", body=BODY, offline=True)

        self.assertEqual(self.candidate("send").returncode, 0)
        self.assertEqual(self.queue.read_text().strip(), "my note")
        call = self.gh_calls()[-1]
        self.assertEqual(call[:6], ["issue", "create", "-l", "candidate", "-t", "first"])

    def test_an_entry_is_sent_without_its_queue_trailer(self):
        self.candidate("file", "-t", "first", body=BODY, offline=True)
        self.candidate("comment", "12", body="more\n", offline=True)

        _, entries = queued(self.queue.read_text())
        self.assertEqual([(title, body) for _, title, body in entries],
                         [("first", BODY.strip()), ("comment on #12", "more")])


if __name__ == "__main__":
    unittest.main()

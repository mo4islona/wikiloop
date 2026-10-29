"""What a gardener re-verify session is told. No network: `gh` is replaced."""
from __future__ import annotations

import json
import unittest
from datetime import date

from wikiloop import gardener

SOURCE = "https://github.com/acme/api/tree/main/apps/auth"
CFG = {"lint": {"stale_days": 90}, "core": {"path": "core"}}


def api_commit(i: int) -> dict:
    sha = f"{i:07x}" + "f" * 33
    return {
        "sha": sha,
        "commit": {"message": f"feat: change {i}\n\nbody", "committer": {"date": f"2026-10-{i % 28 + 1:02d}T00:00:00Z"}},
        "html_url": f"https://github.com/acme/api/commit/{sha}",
    }


class FakeGh:
    def __init__(self, commits: int):
        self.calls = []
        self.commits = commits

    def __call__(self, *args: str) -> str:
        self.calls.append(args)
        return "".join(json.dumps(api_commit(i)) + "\n" for i in range(self.commits))


class Gardener(unittest.TestCase):
    def setUp(self):
        self.real_gh = gardener.gh

    def tearDown(self):
        gardener.gh = self.real_gh

    def finding(self, commits: list[dict]) -> dict:
        return {"skill": "debug-checkout", "owner": "EF", "verified": "2026-09-01", "age": 58,
                "changed": [{"url": SOURCE, "commits": commits}]}

    def commits(self, n: int) -> list[dict]:
        gardener.gh = FakeGh(n)
        return gardener.commits_since(SOURCE, date(2026, 9, 1))

    def test_every_page_is_read(self):
        self.assertEqual(len(self.commits(130)), 130)
        self.assertIn("--paginate", gardener.gh.calls[0])

    def test_session_gets_every_commit(self):
        commits = self.commits(8)
        prompt = gardener.session_prompt(CFG, self.finding(commits))

        for c in commits:
            self.assertIn(c["sha"], prompt)
        self.assertNotIn("more", prompt.split("Your job")[0])
        self.assertNotIn("could not be read", prompt)

    def test_console_report_stays_short(self):
        report = gardener.render([self.finding(self.commits(8))], 90)
        self.assertIn("… and 3 more", report)

    def test_unread_source_keeps_the_date(self):
        finding = self.finding([{"error": "HTTP 404"}])
        read = {"sha": "abc1234", "date": "2026-10-01", "title": "feat: x", "url": "https://github.com/acme/web/commit/abc1234"}
        finding["changed"].append({"url": "https://github.com/acme/web", "commits": [read]})
        prompt = gardener.session_prompt(CFG, finding)

        self.assertIn(f"These sources could not be read: {SOURCE}.", prompt)
        self.assertIn("do not change `last-verified`", prompt)


if __name__ == "__main__":
    unittest.main()

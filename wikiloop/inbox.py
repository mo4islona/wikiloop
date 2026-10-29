"""The inbox: where candidates land. One adapter per tracker; this version has GitHub issues."""
from __future__ import annotations

import json
import subprocess
import tempfile


class InboxError(Exception):
    pass


class GitHubInbox:
    """Candidates are issues with one label in one repo; `gh` must be logged in."""

    def __init__(self, repo: str, label: str):
        self.repo = repo
        self.label = label

    def gh(self, *args: str) -> str:
        try:
            proc = subprocess.run(["gh", *args, "-R", self.repo], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise InboxError(f"gh: {e}") from None

        if proc.returncode != 0:
            raise InboxError(proc.stderr.strip() or f"gh {args[0]} {args[1]} failed")
        return proc.stdout

    def search(self, query: str, state: str = "open") -> list[dict]:
        out = self.gh("issue", "list", "-l", self.label, "--state", state, "--search", query,
                      "--limit", "30", "--json", "number,title,url,labels")
        return json.loads(out or "[]")

    def file(self, title: str, body: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".md") as f:
            f.write(body)
            f.flush()
            return self.gh("issue", "create", "-l", self.label, "-t", title, "--body-file", f.name).strip()

    def comment(self, number: int, body: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".md") as f:
            f.write(body)
            f.flush()
            return self.gh("issue", "comment", str(number), "--body-file", f.name).strip()


def make_inbox(cfg: dict) -> GitHubInbox:
    inbox = cfg["inbox"]
    if inbox["kind"] != "github":
        raise InboxError(f"no adapter for inbox kind {inbox['kind']!r}")

    return GitHubInbox(inbox["repo"], inbox["label"])

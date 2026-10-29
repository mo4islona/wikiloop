#!/usr/bin/env python3
"""PreToolUse hook: a candidate filed past `wikiloop candidate` must still carry the gate lines.

    python3 candidate_gate.py <plugin root>/hooks/wikiloop.json     # the event JSON on stdin

`wikiloop candidate file` checks the lines itself. This hook covers the bypass: a raw
`gh issue create` with the inbox label into the inbox repo. When the body lacks a line that
`[gate] required` names, the call is denied with the template, so the session fixes the body in
the same turn instead of triage closing it a week later.

The body is read from the command (`-b`, a heredoc) and from a `--body-file`. A body built with
`$(cat file)` is invisible here; the reason says to pass the file instead.
Deterministic, no network, no model call.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

FILING = re.compile(r"\bgh\s+issue\s+create\b")
ANY_REPO = re.compile(r"(?:^|\s)(?:-R|--repo)[=\s]")
BODY_FILE = re.compile(r"(?:^|\s)(?:-F|--body-file)[=\s]+(['\"]?)([^\s'\"]+)\1")


def files_candidate(command: str, cwd: str, cfg: dict) -> bool:
    """A `gh issue create` with the inbox label that lands in the inbox repo."""
    label = re.escape(cfg["inbox"]["label"])
    labelled = re.compile(rf"(?:^|\s)(?:-l|--label)[=\s]+['\"]?[\w,-]*\b{label}\b")
    if not FILING.search(command) or not labelled.search(command):
        return False

    repo = re.compile(rf"\b{re.escape(cfg['inbox']['repo'].split('/')[-1])}\b")
    if repo.search(command):
        return True

    # No -R: gh files into the repo of the working directory.
    return not ANY_REPO.search(command) and bool(repo.search(cwd))


def body_text(command: str, cwd: str) -> str:
    """The command itself plus any --body-file it names."""
    text = command
    for _, name in BODY_FILE.findall(command):
        if name == "-":
            continue

        path = Path(name) if Path(name).is_absolute() else Path(cwd) / name
        try:
            text += "\n" + path.read_text()
        except (OSError, UnicodeDecodeError):
            pass
    return text


def missing_lines(body: str, cfg: dict) -> list[str]:
    keys = [r["key"] for r in cfg["gate"]["required"]]
    return [key for key in keys if not re.search(re.escape(key), body, re.IGNORECASE)]


def main() -> int:
    cfg = common.load_config()
    payload = common.read_payload()
    if cfg is None or payload.get("tool_name") != "Bash":
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    if isinstance(command, list):  # Codex may pass argv
        command = " ".join(str(c) for c in command)
    cwd = payload.get("cwd") or ""
    if not files_candidate(command, cwd, cfg):
        return 0

    missing = missing_lines(body_text(command, cwd), cfg)
    if not missing:
        return 0

    named = " and ".join(f"a `{m}:` line" for m in missing)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": common.fill(cfg["texts"]["gate_reason"], {"missing": named}),
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

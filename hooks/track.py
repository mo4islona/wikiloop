#!/usr/bin/env python3
"""PostToolUse and UserPromptSubmit hook: log investigation steps and human replies.

    python3 track.py <plugin root>/hooks/wikiloop.json     # the event JSON on stdin

Appends to the session's event log and prints nothing, so it never changes what the agent
sees. The Stop hook decides from the log. Silent on any error: a broken log must never block
a tool call or a prompt.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def main() -> int:
    cfg = common.load_config()
    payload = common.read_payload()
    if cfg is None or not payload:
        return 0

    sig = common.Signals(cfg)
    event = payload.get("hook_event_name", "")
    if event == "UserPromptSubmit":
        evs = sig.prompt(payload.get("prompt", ""))
    else:
        evs = sig.tool(payload.get("tool_name", ""), payload.get("tool_input") or {})

    if evs:
        try:
            common.append_events(cfg["wiki"]["plugin"], payload.get("session_id", ""), evs)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

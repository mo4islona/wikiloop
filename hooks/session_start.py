#!/usr/bin/env python3
"""SessionStart hook: hand every session the rules that make the wiki the single store, and
record where the session's investigation count starts.

    python3 session_start.py <plugin root>/hooks/wikiloop.json     # the event JSON on stdin

Printed once per session, a few hundred tokens. No network, no model call.

The baseline is for the Stop hook: a resumed session keeps its event log, and without a
baseline the first turn after resume would be asked to file candidates about days-old work.
Only steps after this point count.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def record_baseline(cfg: dict, session_id: str) -> None:
    plugin = cfg["wiki"]["plugin"]
    sig = common.Signals(cfg)
    evs = common.read_events(plugin, session_id)
    weight, _, _ = common.investigation(evs, sig, cfg["investigation"]["threshold"])

    common.write_state(plugin, session_id, {**common.read_state(plugin, session_id), "baseline": weight})


def main() -> int:
    cfg = common.load_config()
    payload = common.read_payload()
    if cfg is None:
        return 0

    try:
        record_baseline(cfg, payload.get("session_id", ""))
    except OSError:
        pass  # the rules still go out; the Stop hook falls back to counting from zero

    plugin = cfg["wiki"]["plugin"]
    values = {
        "root": common.plugin_root(),
        "candidate": common.candidate_command(cfg),
        "transcript": payload.get("transcript_path") or "",
        "cache": common.cache_dir(plugin),
        "queued": common.queued(plugin),
    }
    context = common.fill(cfg["texts"]["session_rule"], values)

    # .get: a config built by an older core has no such text, and the rules must still go out
    queued_text = cfg["texts"].get("session_queued")
    if values["queued"] and queued_text:
        context += " " + common.fill(queued_text, values)

    has_report = cfg["report_session"]["kind"] != "none" and payload.get("transcript_path")
    if has_report:
        context += " " + common.fill(cfg["texts"]["session_report"], values)

    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

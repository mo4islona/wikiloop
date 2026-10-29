#!/usr/bin/env python3
"""Stop hook: a session that investigated a live system files what it learned as a candidate.

    python3 stop.py <plugin root>/hooks/wikiloop.json      # the event JSON on stdin

Reads the session's event log (written by track.py) and weighs investigation steps. Once
`threshold` new steps have happened the hook blocks the stop once and hands the agent an
instruction: grep the wiki and the open candidates, then file a candidate if the session found
a fact the wiki lacks, or answer "wiki: nothing new".

Two guards decide *when* it asks, because a conclusion the agent has just produced is not yet a
fact. It asks only once the user has replied after the last investigation step: the finding has
been read, and a wrong one has had its chance to be challenged. And it counts from a baseline
the SessionStart hook records, so a resumed session is not asked about its history.

The reply guard also keeps it quiet in one-shot runs (`claude -p`, `codex exec`): no human
replies after the steps. Claude Code's other surfaces show only a turn's last message, which
after a block is the reply to the hook, so under Claude it asks in the interactive CLI only.

State: `<session>.json` beside the event log: `baseline` and `asked`, the step weights at the
session's start and when it last asked. A long session is asked again after `reask` more steps.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def silenced(payload: dict) -> bool:
    if payload.get("stop_hook_active"):
        return True

    is_claude = common.agent(payload) == "claude"
    return is_claude and os.environ.get("CLAUDE_CODE_ENTRYPOINT") != "cli"


def main() -> int:
    cfg = common.load_config()
    payload = common.read_payload()
    if cfg is None or silenced(payload):
        return 0

    plugin = cfg["wiki"]["plugin"]
    session_id = payload.get("session_id", "")
    sig = common.Signals(cfg)
    inv = cfg["investigation"]

    evs = common.read_events(plugin, session_id)
    weight, kinds, last = common.investigation(evs, sig, inv["threshold"])

    state = common.read_state(plugin, session_id)
    baseline = state.get("baseline", 0)
    asked = state.get("asked", 0)
    if weight - baseline < inv["threshold"]:
        return 0
    if asked and weight - asked < inv["reask"]:
        return 0

    after = evs[last + 1:]
    handled = any(k == "filed" or (k == "skill" and d == sig.contribute_skill) for k, d in after)
    answered = any(k == "human" for k, _ in after)
    if handled or not answered:
        return 0

    common.write_state(plugin, session_id, {**state, "asked": weight})

    seen = sorted(set(kinds))
    reason = common.fill(cfg["texts"]["stop_reason"], {
        "n": weight - max(baseline, asked),
        "kinds": ", ".join(seen[:6]),
        "root": common.plugin_root(),
        "candidate": common.candidate_command(cfg),
        "cache": common.cache_dir(plugin),
        "reask": inv["reask"],
    })
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

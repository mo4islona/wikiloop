"""`wikiloop check`: do the rails still hold with this wiki's config?

The config tunes the loop; it cannot switch it off. This command runs the real hooks against
synthetic sessions built from the wiki's own `[investigation]` and `[gate]`, and checks:

- the generated files match the config (the same test as `wikiloop build --check`);
- a vendored core is unmodified (its tree hash matches `core/.wikiloop-core.json`);
- under Claude Code and under Codex alike, the Stop hook stays silent until the user has
  replied, then asks once; under Claude Code it never asks outside the interactive CLI;
- the SessionStart hook hands out the rule that names this plugin;
- a candidate without the gate lines is refused, by the hook and by `wikiloop candidate`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from wikiloop import build, vendor
from wikiloop.candidate import missing_lines
from wikiloop.config import CORE, RESOLVED_PATH

HOOKS = CORE / "hooks"


def one_step(cfg: dict) -> dict | None:
    """A tool call the wiki's config counts as one investigation step; None if none can be made."""
    inv = cfg["investigation"]
    if inv["commands"]:
        return {"tool_name": "Bash", "tool_input": {"command": f"{inv['commands'][0]} --help"}}
    if inv["mcp_tools"]:
        return {"tool_name": inv["mcp_tools"][0].replace("*", "x"), "tool_input": {}}
    return None


def debug_skill(cfg: dict) -> dict | None:
    patterns = cfg["investigation"]["debug_skills"]
    if not patterns:
        return None
    return {"tool_name": "Skill", "tool_input": {"skill": f"{cfg['wiki']['plugin']}:{patterns[0].replace('*', 'x')}"}}


def run_hook(script: str, payload: dict, config: Path, cache: str, env_extra: dict) -> dict | None:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_ENTRYPOINT", "PLUGIN_ROOT")}
    env.update({"XDG_CACHE_HOME": cache, "CLAUDE_PLUGIN_ROOT": str(config.parent.parent), **env_extra})
    proc = subprocess.run([sys.executable, str(HOOKS / script), str(config)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"{script} exited {proc.returncode}: {proc.stderr.strip()[-300:]}")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def asks(out: dict | None) -> bool:
    return bool(out and out.get("decision") == "block")


# How each agent runs the hooks: Claude Code names its surface, Codex sets PLUGIN_ROOT and turn ids.
AGENTS = {
    "Claude Code": ({"CLAUDE_CODE_ENTRYPOINT": "cli"}, {}),
    "Codex": ({"PLUGIN_ROOT": "/plugin"}, {"turn_id": "turn-check"}),
}


class Session:
    """One synthetic session: its tool calls and replies go through track.py, its stops through stop.py."""

    def __init__(self, name: str, config: Path, cache: str, env: dict, extra: dict):
        self.payload = {"session_id": name, "transcript_path": None, **extra}
        self.config, self.cache, self.env = config, cache, env

    def tool(self, call: dict) -> None:
        run_hook("track.py", {**self.payload, "hook_event_name": "PostToolUse", **call}, self.config, self.cache, self.env)

    def reply(self) -> None:
        payload = {**self.payload, "hook_event_name": "UserPromptSubmit", "prompt": "ok, makes sense"}
        run_hook("track.py", payload, self.config, self.cache, self.env)

    def stop(self, env: dict | None = None) -> bool:
        payload = {**self.payload, "hook_event_name": "Stop", "stop_hook_active": False}
        return asks(run_hook("stop.py", payload, self.config, self.cache, env if env is not None else self.env))


def stop_rails(cfg: dict, config: Path, cache: str) -> list[tuple[str, bool]]:
    step = one_step(cfg)
    steps = [step] * cfg["investigation"]["threshold"] if step else [debug_skill(cfg)]
    if steps == [None]:
        return [("Stop hook: no signal can be synthesized from `[investigation]`; checked by its unit tests only", True)]

    results = []
    for name, (env, extra) in AGENTS.items():
        def session(label: str) -> Session:
            return Session(f"check-{name}-{label}".replace(" ", "-"), config, cache, env, extra)

        unanswered = session("a")
        for s in steps:
            unanswered.tool(s)

        answered = session("b")
        for s in steps:
            answered.tool(s)
        answered.reply()

        results += [
            (f"{name}: the Stop hook stays silent before the user replies", not unanswered.stop()),
            (f"{name}: the Stop hook asks after the user replied", answered.stop()),
            (f"{name}: the Stop hook asks once", not answered.stop()),
        ]

    claude_env, claude_extra = AGENTS["Claude Code"]
    print_only = Session("check-claude-print", config, cache, claude_env, claude_extra)
    for s in steps:
        print_only.tool(s)
    print_only.reply()
    results.append(("Claude Code: the Stop hook stays silent outside the interactive CLI",
                    not print_only.stop({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"})))
    return results


def session_rails(cfg: dict, config: Path, cache: str) -> list[tuple[str, bool]]:
    out = run_hook("session_start.py", {"session_id": "check-s", "transcript_path": ""}, config, cache, {}) or {}
    context = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    return [("SessionStart hook: hands out the rule naming this plugin",
             f"{cfg['wiki']['plugin']}:wiki-contribute" in context)]


def gate_rails(cfg: dict, config: Path, cache: str) -> list[tuple[str, bool]]:
    inbox = cfg["inbox"]
    command = f"gh issue create -R {inbox['repo']} -l {inbox['label']} -t t -b 'Symptom: s'"
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/"}
    out = run_hook("candidate_gate.py", payload, config, cache, {}) or {}
    denied = out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"

    full = "\n".join(f"{r['key']}: x" for r in cfg["gate"]["required"])
    return [
        ("Gate hook: refuses a raw candidate without the gate lines", denied),
        ("wikiloop candidate: refuses a body without the gate lines", bool(missing_lines("Symptom: s", cfg))),
        ("wikiloop candidate: accepts a body with every gate line", not missing_lines(full, cfg)),
    ]


def core_rail(root: Path, cfg: dict) -> list[tuple[str, bool]]:
    core = (root / cfg["core"]["path"]).resolve()
    record = vendor.read_record(core)
    if record is None:
        return [(f"core at {cfg['core']['path']}: not vendored (no {vendor.RECORD}), skipped", True)]

    same = vendor.tree_hash(core) == record.get("tree_hash")
    return [(f"core {record.get('version')}: no local edits (use core-patches/ for a hotfix)", same)]


def main(root: Path, cfg: dict, argv: list[str]) -> int:
    files, _ = build.generate(root, cfg)
    stale = build.diff(root, files)
    results = [("generated files match the config" + (f" ({len(stale)} differ)" if stale else ""), not stale)]
    results += core_rail(root, cfg)

    config = root / RESOLVED_PATH
    if not config.is_file():
        results.append((f"{RESOLVED_PATH} exists (run `wikiloop build`)", False))
    else:
        with tempfile.TemporaryDirectory(prefix="wikiloop-check-") as cache:
            resolved = json.loads(config.read_text())
            for rails in (stop_rails, session_rails, gate_rails):
                results += rails(resolved, config, cache)

    failed = 0
    for name, ok in results:
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}")

    print(f"\n{len(results) - failed}/{len(results)} rails hold")
    return 1 if failed else 0

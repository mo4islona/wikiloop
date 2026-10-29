"""What the hooks share: the resolved config, the signals that count as investigation, the
per-session event log, and the agent the hook runs under.

Investigation is counted from hook events, not from the transcript. `track.py` appends one
line per step (PostToolUse) and per human reply (UserPromptSubmit) to a log per session; the
Stop hook reads only that log. Both agents send the same event fields, and neither promises a
stable transcript format, so the log is the one input the hooks own.

Deterministic, no network, no model call. Runs on python3 3.9 and later.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from pathlib import Path

# Prompts the harness writes into the user slot: hook feedback, task notifications, slash
# commands, compaction summaries, interrupts. None of them is the user typing.
INJECTED = ("<", "/", "[", "Stop hook feedback", "This session is being continued")
SKILL_FILE = re.compile(r"skills/([a-z0-9][a-z0-9-]*)/SKILL\.md")
# The header of an entry `wikiloop candidate` queued while the tracker was out of reach.
QUEUED = re.compile(r"^## \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ — ", re.MULTILINE)


def config_path() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    return Path(os.environ.get("CLAUDE_PLUGIN_ROOT", ".")) / "hooks" / "wikiloop.json"


def load_config() -> dict | None:
    try:
        return json.loads(config_path().read_text())
    except (OSError, ValueError):
        return None


def read_payload() -> dict:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def agent(payload: dict) -> str:
    """`codex` or `claude`. Codex adds `turn_id` to turn events and sets PLUGIN_ROOT for plugin hooks."""
    is_codex = "turn_id" in payload or bool(os.environ.get("PLUGIN_ROOT"))
    return "codex" if is_codex else "claude"


class Signals:
    """What counts as investigation, compiled from `[investigation]`."""

    def __init__(self, cfg: dict):
        self.plugin = cfg["wiki"]["plugin"]
        plugin = re.escape(self.plugin)
        inv = cfg["investigation"]

        # fnmatch.translate anchors each pattern at the end already
        debug = "|".join(fnmatch.translate(p) for p in inv["debug_skills"])
        self.debug_skill = re.compile(rf"^{plugin}:(?:{debug})") if debug else None
        self.contribute_skill = f"{self.plugin}:wiki-contribute"
        self.typed = re.compile(rf"^/({plugin}:[a-z0-9-]+)")

        words = [rf"\b{re.escape(c)}\b" for c in inv["commands"]]
        shell = "|".join(words + [f"(?:{p})" for p in inv["patterns"]])
        self.shell = re.compile(shell) if shell else None
        self.mcp_tools = inv["mcp_tools"]

        # Commenting on an open candidate handles a finding as fully as filing a new one.
        repo = re.escape(cfg["inbox"]["repo"].split("/")[-1])
        self.filed = re.compile(rf"wikiloop\s+candidate\s+(?:file|comment)\b|gh issue (?:create|comment)\b.*\b{repo}\b")

    def tool(self, name: str, inp: dict) -> list[tuple[str, str]]:
        """Events for one finished tool call."""
        if name == "Skill" and inp.get("skill"):
            return [("skill", inp["skill"])]

        if name == "Bash":
            return self.command(inp.get("command", ""))

        is_mcp = any(fnmatch.fnmatchcase(name, pattern) for pattern in self.mcp_tools)
        return [("mcp", name)] if is_mcp else []

    def command(self, cmd) -> list[tuple[str, str]]:
        if isinstance(cmd, list):  # Codex may pass argv
            cmd = " ".join(str(c) for c in cmd)
        if self.filed.search(cmd):
            return [("filed", cmd[:200])]

        # An agent without a Skill tool loads a skill by reading its SKILL.md.
        read_skill = SKILL_FILE.search(cmd)
        if read_skill:
            return [("skill", f"{self.plugin}:{read_skill.group(1)}")]

        hit = self.shell.search(cmd) if self.shell else None
        return [("shell", hit.group(0))] if hit else []

    def prompt(self, text: str) -> list[tuple[str, str]]:
        """Events for a submitted prompt: a typed skill command, a human reply, or nothing."""
        stripped = (text or "").lstrip()
        typed = self.typed.match(stripped)
        if typed:
            return [("skill", typed.group(1))]
        if stripped and not stripped.startswith(INJECTED):
            return [("human", "")]
        return []


def investigation(evs: list[tuple[str, str]], sig: Signals, threshold: int) -> tuple[int, list[str], int]:
    """Weight of investigation steps, their kinds, and the index of the last one."""
    weight, kinds, last = 0, [], -1
    for i, (kind, detail) in enumerate(evs):
        if kind == "skill" and sig.debug_skill and sig.debug_skill.match(detail):
            weight += threshold
        elif kind in ("shell", "mcp"):
            weight += 1
        else:
            continue

        kinds.append(detail)
        last = i
    return weight, kinds, last


def cache_dir(plugin: str) -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / plugin


def queued(plugin: str) -> int:
    try:
        return len(QUEUED.findall((cache_dir(plugin) / "candidates.md").read_text()))
    except OSError:
        return 0


def session_file(plugin: str, session_id: str, suffix: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", session_id or "unknown")
    return cache_dir(plugin) / "sessions" / f"{safe}.{suffix}"


def append_events(plugin: str, session_id: str, evs: list[tuple[str, str]]) -> None:
    """One line per event; an append of a short line is atomic, so parallel tool calls do not race."""
    path = session_file(plugin, session_id, "events")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps({"k": k, "d": d}) + "\n" for k, d in evs)
    with path.open("a") as f:
        f.write(lines)


def read_events(plugin: str, session_id: str) -> list[tuple[str, str]]:
    out = []
    try:
        with session_file(plugin, session_id, "events").open() as f:
            for line in f:
                try:
                    e = json.loads(line)
                    out.append((e["k"], e["d"]))
                except (ValueError, KeyError):
                    continue
    except OSError:
        pass
    return out


def read_state(plugin: str, session_id: str) -> dict:
    try:
        return json.loads(session_file(plugin, session_id, "json").read_text())
    except (OSError, ValueError):
        return {}


def write_state(plugin: str, session_id: str, state: dict) -> None:
    path = session_file(plugin, session_id, "json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def plugin_root() -> str:
    return os.environ.get("CLAUDE_PLUGIN_ROOT") or os.environ.get("PLUGIN_ROOT") or "<plugin root>"


def candidate_command(cfg: dict) -> str:
    return f"python3 {plugin_root()}/{cfg['core']['path']}/bin/wikiloop candidate"


def fill(text: str, values: dict) -> str:
    """Runtime placeholders only: the texts carry other braces, so no str.format."""
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text

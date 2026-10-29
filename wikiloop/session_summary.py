"""`wikiloop session-summary <transcript.jsonl> [--from ISO]`: where a session spent its time
and tokens.

Prints, for the whole transcript or from a timestamp on: what the user typed and when, every
tool the agent called, which skills it loaded, each Stop-hook block, the largest tool results,
the API calls that rebuilt the prompt cache, and the token totals. Enough to answer "what did
the plugin cost here" without a read of the whole file.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

INJECTED = ("<", "/", "[", "Stop hook feedback", "This session is being continued", "## Context Usage")
BIG_RESULT = 8_000       # characters
CACHE_REBUILD = 20_000   # cache_creation_input_tokens in one call


def load(path: Path, since: str) -> list[dict]:
    out = []
    with path.open() as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since and (e.get("timestamp") or since) < since:
                continue
            out.append(e)
    return out


def clock(e: dict) -> str:
    return (e.get("timestamp") or "")[5:16].replace("T", " ")


def one_line(s: str, n: int = 110) -> str:
    return " ".join(str(s).split())[:n]


class Summary:
    def __init__(self) -> None:
        self.tools: Counter = Counter()
        self.skills: Counter = Counter()
        self.results: list[tuple[int, str, str]] = []
        self.last_cmd: dict[str, str] = {}
        self.rebuilds: list[tuple[str, int]] = []
        self.usage: dict[str, dict] = {}
        self.humans: list[tuple[str, str]] = []
        self.blocks: list[tuple[str, str]] = []
        self.turns: list[tuple[str, int]] = []

    def assistant(self, e: dict, msg: dict) -> None:
        usage = msg.get("usage") or {}
        is_new_call = msg.get("id") and msg["id"] not in self.usage
        if msg.get("id"):
            self.usage[msg["id"]] = usage
        if is_new_call and usage.get("cache_creation_input_tokens", 0) >= CACHE_REBUILD:
            self.rebuilds.append((clock(e), usage["cache_creation_input_tokens"]))

        for b in msg.get("content") or []:
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue

            inp = b.get("input", {}) or {}
            self.tools[b.get("name", "?")] += 1
            if b.get("name") == "Skill":
                self.skills[inp.get("skill", "?")] += 1
            self.last_cmd[b.get("id", "")] = one_line(inp.get("command") or inp.get("skill") or inp.get("file_path") or "")

    def user(self, e: dict, content) -> None:
        if isinstance(content, str):
            text = content.lstrip()
            if not e.get("isMeta") and text and not text.startswith(INJECTED):
                self.humans.append((clock(e), one_line(content, 120)))
            elif text.startswith("Stop hook feedback"):
                reason = content.split("\n", 2)[1] if "\n" in content else content
                self.blocks.append((clock(e), one_line(reason, 120)))
            return

        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                size = len(json.dumps(b.get("content", "")))
                if size >= BIG_RESULT:
                    self.results.append((size, clock(e), self.last_cmd.get(b.get("tool_use_id", ""), "?")))

    def print(self) -> None:
        print("\n== user typed ==")
        for t, text in self.humans:
            print(f"  {t}  {text}")

        print("\n== tools ==")
        for name, n in self.tools.most_common():
            print(f"  {n:5d}  {name}")
        if self.skills:
            print("\n== skills loaded ==")
            for name, n in self.skills.most_common():
                print(f"  {n:5d}  {name}")

        print(f"\n== stop hook blocked the turn: {len(self.blocks)} ==")
        for t, text in self.blocks:
            print(f"  {t}  {text}")

        print("\n== turns (seconds) ==")
        print("  " + "  ".join(f"{t[6:]}:{s}s" for t, s in self.turns))

        print(f"\n== tool results over {BIG_RESULT} chars ==")
        for size, t, cmd in sorted(self.results, reverse=True)[:10]:
            print(f"  {size:7d}  {t}  {cmd}")

        print(f"\n== prompt-cache rebuilds over {CACHE_REBUILD} tokens ==")
        for t, cc in self.rebuilds:
            print(f"  {t}  {cc}")

        keys = ("cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
        tot = {k: sum(u.get(k, 0) for u in self.usage.values()) for k in keys}
        print(f"\n== tokens: {len(self.usage)} API calls ==")
        print(f"  cache read {tot['cache_read_input_tokens']:,}  cache write {tot['cache_creation_input_tokens']:,}"
              f"  output {tot['output_tokens']:,}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    since = argv[2] if len(argv) > 2 and argv[1] == "--from" else ""
    entries = load(Path(argv[0]), since)
    if not entries:
        print("no records")
        return 1

    stamps = [e["timestamp"] for e in entries if e.get("timestamp")]
    print(f"session {entries[0].get('sessionId', '?')}: {len(entries)} records, {stamps[0][:16]} .. {stamps[-1][:16]}")

    summary = Summary()
    for e in entries:
        kind = e.get("type")
        msg = e.get("message", {}) or {}
        if kind == "assistant":
            summary.assistant(e, msg)
        elif kind == "user":
            summary.user(e, msg.get("content"))
        elif kind == "system" and e.get("subtype") == "turn_duration":
            summary.turns.append((clock(e), int((e.get("durationMs") or 0) / 1000)))

    summary.print()
    return 0

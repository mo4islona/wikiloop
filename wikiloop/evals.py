"""`wikiloop evals`: do skill descriptions catch how people phrase the task?

    wikiloop evals                         # every case, runs from its frontmatter
    wikiloop evals --case 'checkout-*' --runs 1
    wikiloop evals --threshold 0.66 --jobs 4 --model opus

Cases are the wiki's `evals/*/` plus the core's negative cases (`evals/negative/*/` in the core):
prompts no wiki skill fits. Each case is one prompt and one grader: `loads-skill.md` names the
skill the agent must load first; a grader with `max: 0` says no wiki skill may load. The agent
gets one turn and no tool but Skill, so a run is one model call over the system prompt. The
layout is the one `claude plugin eval` reads. Needs `claude` logged in (or ANTHROPIC_API_KEY).
Exit 1 if any case scores below the threshold.

A run loads no user settings and no MCP servers, and saves no transcript: the maintainer's own
plugins, hooks and servers would change what the agent sees, and an installed copy of this wiki
would compete with the checkout. Auth set in user settings (`apiKeyHelper`, `env`) is not read.
"""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from wikiloop.config import CORE

FRONT = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)


def frontmatter(path: Path) -> tuple[dict, str]:
    m = FRONT.match(path.read_text())
    fields = dict(re.findall(r"^([a-z_]+):\s*(.*)$", m.group(1), re.M))
    return fields, m.group(2).strip()


def case_dirs(root: Path) -> list[Path]:
    dirs = []
    for base in (root / "evals", CORE / "evals" / "negative"):
        if base.is_dir():
            dirs += [p for p in base.iterdir() if p.is_dir() and (p / "prompt.md").exists()]
    return sorted(dirs, key=lambda p: p.name)


def load_cases(root: Path, plugin: str, pattern: str | None) -> list[dict]:
    cases = []
    for d in case_dirs(root):
        if pattern and not fnmatch.fnmatch(d.name, pattern):
            continue

        fm, prompt = frontmatter(d / "prompt.md")
        grader, _ = frontmatter(next((d / "graders").glob("*.md")))
        want = re.search(rf"{re.escape(plugin)}:([a-z0-9-]+)", grader.get("input_match", ""))
        is_negative = grader.get("max") == "0"
        cases.append({"name": d.name, "prompt": prompt, "runs": int(fm.get("runs", 3)),
                      "expect": None if is_negative or not want else want.group(1)})
    return cases


def skills_loaded(root: Path, prompt: str, model: str | None) -> list[str]:
    """Skill names the agent invoked in its first turn."""
    # An empty cwd: in the wiki checkout the model greps the files instead of loading a skill.
    with tempfile.TemporaryDirectory(prefix="trigger-eval-") as cwd:
        proc = subprocess.run(
            ["claude", "-p", "--output-format", "stream-json", "--verbose", "--max-turns", "1",
             "--setting-sources", "project,local", "--strict-mcp-config", "--no-session-persistence",
             "--allowedTools", "Skill", "--plugin-dir", str(root),
             *(["--model", model] if model else []), prompt],
            capture_output=True, text=True, cwd=cwd, stdin=subprocess.DEVNULL,
        )

    loaded, answered, failure = [], False, None
    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Hitting max turns (the agent wanted a tool it was not granted) is a normal end.
        if msg.get("type") == "result" and msg.get("is_error") and msg.get("subtype") != "error_max_turns":
            failure = msg.get("subtype") or "error"
        if msg.get("type") != "assistant":
            continue

        answered = True
        for block in msg.get("message", {}).get("content", []):
            if block.get("type") != "tool_use":
                continue
            if block.get("name") == "Skill":
                loaded.append(block.get("input", {}).get("skill", ""))
            else:
                arg = str(block.get("input", {}).get("command", ""))[:40]
                loaded.append(f"<{block.get('name')}{' ' + arg if arg else ''}>")

    if failure or not answered:
        loaded.append(f"<error: {failure or proc.stderr.strip()[-120:] or 'no answer'}>")
    return loaded


def score(root: Path, plugin: str, case: dict, runs: int, model: str | None) -> dict:
    results = []
    for _ in range(runs):
        loaded = skills_loaded(root, case["prompt"], model)
        wiki = [s for s in loaded if s.startswith(f"{plugin}:")]
        errored = any(s.startswith("<error") for s in loaded)
        hit = (f"{plugin}:{case['expect']}" in wiki) if case["expect"] else not wiki
        results.append((not errored and hit, loaded))
    return {**case, "score": sum(ok for ok, _ in results) / runs, "loaded": [l for _, l in results]}


def main(root: Path, cfg: dict, argv: list[str]) -> int:
    opt = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d
    pattern, runs, jobs = opt("--case"), opt("--runs"), int(opt("--jobs", 4))
    threshold = float(opt("--threshold", cfg["evals"]["threshold"]))
    model = opt("--model", cfg["evals"]["model"] or None)  # triggering differs per model, so pin one
    plugin = cfg["wiki"]["plugin"]

    cases = load_cases(root, plugin, pattern)
    if not cases:
        print("no cases matched")
        return 2

    with ThreadPoolExecutor(jobs) as pool:
        results = list(pool.map(lambda c: score(root, plugin, c, int(runs) if runs else c["runs"], model), cases))

    failed = 0
    for r in results:
        mark = "ok  " if r["score"] >= threshold else "FAIL"
        failed += mark == "FAIL"
        got = "; ".join(",".join(l) or "-" for l in r["loaded"])
        print(f"{mark} {r['score']:.2f} {r['name']:28} want {r['expect'] or '(none)':20} got {got}")

    print(f"\n{len(results) - failed}/{len(results)} cases at or above {threshold}")
    return 1 if failed else 0

"""`wikiloop shepherd`: the next actions for one pass of the wiki shepherd. No model call.

    wikiloop shepherd           # one line per action, most urgent first
    wikiloop shepherd --json
    wikiloop apply pairs.json   # apply exact OLD -> NEW pairs; each OLD must match exactly once

State lives on GitHub only: each shepherd comment on a PR starts with
`<!-- shepherd round=N verdict=V sha=SHA -->`, and `needs-human` parks a PR or a candidate.
Drafts are never listed.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

MARK = re.compile(r"<!-- shepherd round=(\d+) verdict=(\w+) sha=([0-9a-f]{7,40}) -->")
CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)
LAND_BRANCH = "wiki/land-"
ORDER = ["merge", "apply", "rebase", "review", "escalate", "land", "triage",
         "wait-checks", "wait-land", "wait-human"]


def gh(repo: str, *args: str):
    proc = subprocess.run(["gh", *args, "-R", repo], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def check_result(check: dict) -> str:
    """`pending`, `passed` or `failed` for one rollup entry.

    A check run has `status` and `conclusion`; a commit status from an external CI has only
    `state`, so reading it as a check run would leave it pending forever.
    """
    is_status = check.get("__typename") == "StatusContext" or ("state" in check and "status" not in check)
    if is_status:
        if check["state"] in ("PENDING", "EXPECTED"):
            return "pending"
        return "passed" if check["state"] == "SUCCESS" else "failed"

    if check.get("status") != "COMPLETED":
        return "pending"
    return "passed" if check.get("conclusion") in ("SUCCESS", "SKIPPED", "NEUTRAL") else "failed"


def checks_state(rollup: list) -> str:
    if not rollup:
        return "none"

    results = {check_result(c) for c in rollup}
    if "pending" in results:
        return "pending"
    if results == {"passed"}:
        return "green"
    return "red"


def current_round(marks: list) -> int:
    """Rounds since the last block, close or escalate: a push after one of them starts over."""
    rounds = 0
    for m in reversed(marks):
        if m.group(2) not in ("fix", "merge"):
            break
        rounds += 1
    return rounds


def pr_action(pr: dict, max_rounds: int) -> tuple[str, str]:
    labels = {l["name"] for l in pr["labels"]}
    marks = [m for m in (MARK.search(c["body"]) for c in pr["comments"]) if m]
    last = marks[-1] if marks else None
    head = pr["headRefOid"]
    reviewed_head = last is not None and head.startswith(last.group(3))

    if "needs-human" in labels:
        if reviewed_head:
            return "wait-human", "needs-human; head unchanged since the last shepherd comment"
        return "review", "head moved after needs-human: drop the label, round 1"

    if pr["mergeable"] == "CONFLICTING":
        return "rebase", "conflicts with main: merge origin/main into the branch"

    if not reviewed_head:
        rounds = current_round(marks)
        if rounds >= max_rounds:
            return "escalate", f"{rounds} review rounds without a merge verdict"
        context = f", last reviewed {last.group(3)[:7]}" if last else ""
        return "review", f"round {rounds + 1}{context}"

    verdict = last.group(2)
    if verdict == "fix":
        return "apply", f"round {last.group(1)} findings in the last shepherd comment"
    if verdict != "merge":
        # the run labels a PR when it posts one of these: no label means a person removed it
        return "review", f"needs-human removed after verdict {verdict}: round 1"

    checks = checks_state(pr["statusCheckRollup"])
    if checks == "green":
        return "merge", "verdict merge, checks green"
    if checks == "red":
        return "escalate", "verdict merge but checks red"
    return "wait-checks", f"checks {checks}"


def candidate_action(issue: dict, covered: set[int], land_open: bool) -> dict | None:
    labels = {l["name"] for l in issue["labels"]}
    base = {"kind": "issue", "number": issue["number"], "title": issue["title"]}

    if "needs-human" in labels:
        return {**base, "action": "wait-human", "why": "needs-human"}
    if "triaged" not in labels:
        return {**base, "action": "triage", "why": "no triage verdict"}

    accepted = "blocked" not in labels and issue["number"] not in covered
    if not accepted:
        return None

    priority = next((p for p in ("p1", "p2", "p3") if p in labels), "p?")
    parked = ",parked" if "parked" in labels else ""
    return {**base, "action": "wait-land" if land_open else "land", "why": priority + parked}


def plan(cfg: dict) -> list[dict]:
    max_rounds = cfg["shepherd"]["max_rounds"]
    prs = gh(cfg["wiki"]["repo"], "pr", "list", "--state", "open", "--limit", "100", "--json",
             "number,title,isDraft,headRefOid,headRefName,labels,mergeable,statusCheckRollup,comments,author,body")
    issues = gh(cfg["inbox"]["repo"], "issue", "list", "-l", cfg["inbox"]["label"], "--state", "open",
                "--limit", "200", "--json", "number,title,labels")

    actions = []
    covered: set[int] = set()
    land_open = False
    for pr in prs:
        covered |= {int(n) for n in CLOSES.findall(pr["body"] or "")}
        if pr["isDraft"]:
            continue

        land_open = land_open or pr["headRefName"].startswith(LAND_BRANCH)
        action, why = pr_action(pr, max_rounds)
        actions.append({"action": action, "kind": "pr", "number": pr["number"],
                        "author": pr["author"]["login"], "branch": pr["headRefName"],
                        "head": pr["headRefOid"][:7], "title": pr["title"], "why": why})

    for issue in issues:
        action = candidate_action(issue, covered, land_open)
        if action:
            actions.append(action)

    actions.sort(key=lambda a: (ORDER.index(a["action"]), a["number"]))
    return actions


def main(cfg: dict, argv: list[str]) -> int:
    actions = plan(cfg)
    if "--json" in argv:
        print(json.dumps(actions, indent=1))
        return 0
    if not actions:
        print("nothing to do")
        return 0

    for a in actions:
        who = f" @{a['author']} {a['branch']}@{a['head']}" if a["kind"] == "pr" else ""
        print(f"{a['action']:<11} #{a['number']}{who}  {a['why']}  | {a['title'][:70]}")
    return 0


def apply(argv: list[str]) -> int:
    """Apply exact OLD -> NEW pairs from a JSON list of {file, old, new}; all or nothing."""
    if len(argv) != 1:
        print("usage: wikiloop apply pairs.json")
        return 2

    pairs = json.loads(Path(argv[0]).read_text())
    texts: dict[Path, str] = {}
    for p in pairs:
        path = Path(p["file"])
        text = texts.get(path) or path.read_text()
        count = text.count(p["old"])
        if count != 1:
            print(f"{path}: OLD matches {count} times: {p['old'][:80]!r}")
            return 1
        texts[path] = text.replace(p["old"], p["new"])

    for path, text in texts.items():
        path.write_text(text)
        print(f"updated {path}")
    return 0

"""`wikiloop inbox`: dump the wiki inbox for a triage pass: open candidates and open PRs, with
the wiki files that already mention each candidate's terms. No model call; the judgement is
the agent's.

    wikiloop inbox            # everything open
    wikiloop inbox --new      # candidates without the `triaged` label
    wikiloop inbox --issue N  # one candidate, every term and hit

Runs from a clone of the wiki; needs `gh` logged in.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

STATE_LABELS = ("triaged", "p1", "p2", "p3", "parked", "blocked", "needs-human")
STALE_DAYS = 30

# A term worth grepping: a backticked token, a metric or label name, a file or path.
TERM_RE = re.compile(r"`([^`\n]{3,60})`|\b([A-Za-z][\w.-]*(?:_[\w.-]+)+)\b|\b([\w-]+\.(?:md|ts|yaml|yml|py))\b|\b([\w.-]+/[\w./-]+)\b")


def gh(args: list[str]) -> list[dict] | dict:
    out = subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else []


def age_days(iso: str) -> int:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days


def noise_of(cfg: dict) -> set[str]:
    names = {cfg["wiki"]["plugin"], cfg["wiki"]["repo"], cfg["inbox"]["repo"]}
    return {n.lower() for n in names} | {n.split("/")[-1].lower() for n in names}


def terms_of(text: str, noise: set[str]) -> list[str]:
    seen: list[str] = []
    for m in TERM_RE.finditer(text):
        term = next(g for g in m.groups() if g).strip()
        if len(term) < 4 or term.lower() in noise or term.startswith("http"):
            continue
        if term not in seen:
            seen.append(term)
    return seen[:25]


def wiki_hits(skills: Path, term: str) -> list[str]:
    needle = term.lower()
    return [str(p.relative_to(skills)) for p in sorted(skills.rglob("*.md"))
            if needle in p.read_text(errors="ignore").lower()]


def gate_line(body: str, cfg: dict) -> str | None:
    key = re.escape(cfg["gate"]["required"][0]["key"])
    m = re.search(rf"{key}\**:?\**\s*(.+)", body, re.IGNORECASE)
    return m.group(1).strip() if m else None


def issues(cfg: dict, only_new: bool, one: int | None) -> list[dict]:
    repo, fields = cfg["inbox"]["repo"], "number,title,body,labels,createdAt,updatedAt,comments,author"
    if one:
        rows = [gh(["issue", "view", str(one), "-R", repo, "--json", fields])]
    else:
        rows = gh(["issue", "list", "-R", repo, "-l", cfg["inbox"]["label"], "--state", "open",
                   "--limit", "200", "--json", fields])

    for r in rows:
        r["label_names"] = [l["name"] for l in r["labels"]]
    if only_new:
        rows = [r for r in rows if "triaged" not in r["label_names"]]
    return rows


def prs(cfg: dict) -> list[dict]:
    fields = "number,title,body,files,createdAt,reviewDecision,isDraft,statusCheckRollup,author,reviews"
    rows = gh(["pr", "list", "-R", cfg["wiki"]["repo"], "--state", "open", "--limit", "100", "--json", fields])
    for r in rows:
        r["paths"] = [f["path"] for f in r["files"]]
        r["closes"] = sorted({int(n) for n in re.findall(r"[Cc]loses #(\d+)", r["body"] or "")})
        checks = r.get("statusCheckRollup") or []
        r["checks"] = ",".join(f"{c.get('name') or c.get('context')}={c.get('conclusion') or c.get('state')}"
                               for c in checks) or "none"
    return rows


def print_issue(r: dict, cfg: dict, skills: Path, verbose: bool) -> None:
    state = [l for l in r["label_names"] if l in STATE_LABELS]
    age = age_days(r["createdAt"])
    why = gate_line(r["body"] or "", cfg)

    flags = []
    if age > STALE_DAYS:
        flags.append(f"OLDER THAN {STALE_DAYS}d")
    if not why:
        flags.append(f"NO '{cfg['gate']['required'][0]['key']}' LINE")

    print(f"\n#{r['number']}  {r['title']}")
    print(f"   by @{r['author']['login']}, {age}d old, comments={len(r['comments'])}, state={','.join(state) or 'NEW'}"
          + (f"   <-- {'; '.join(flags)}" if flags else ""))
    if why:
        print(f"   why: {why[:220]}")

    covered = []
    for term in terms_of(r["body"] or "", noise_of(cfg)):
        hits = wiki_hits(skills, term)
        if hits:
            covered.append((term, hits))
        if verbose:
            print(f"   term {term!r}: {', '.join(hits) or '-'}")

    if verbose:
        return
    if covered:
        print("   wiki already mentions: " + "; ".join(f"{t} -> {', '.join(h[:3])}" for t, h in covered[:6]))
    else:
        print("   wiki mentions none of its terms")


def print_pr(r: dict, open_numbers: set[int]) -> None:
    age = age_days(r["createdAt"])
    reviewers = ",".join(sorted({v["author"]["login"] + ":" + v["state"] for v in r.get("reviews", [])})) or "none"

    flags = []
    if age > 7 and reviewers == "none":
        flags.append("UNREVIEWED > 7d")
    if r["isDraft"]:
        flags.append("draft")

    print(f"\nPR #{r['number']}  {r['title']}")
    print(f"   by @{r['author']['login']}, {age}d old, checks={r['checks']}, reviews={reviewers}"
          + (f"   <-- {'; '.join(flags)}" if flags else ""))
    print(f"   files: {', '.join(r['paths'])}")
    if r["closes"]:
        missing = [n for n in r["closes"] if n not in open_numbers]
        print(f"   closes: {r['closes']}" + (f" (not open candidates: {missing})" if missing else ""))


def main(root: Path, cfg: dict, argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wikiloop inbox", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new", action="store_true", help="candidates without the triaged label only")
    ap.add_argument("--issue", type=int, help="one candidate, verbose term report")
    args = ap.parse_args(argv)
    skills = root / "skills"

    rows = issues(cfg, args.new, args.issue)
    print(f"== candidates: {len(rows)} ({'new only' if args.new else 'all open'})")
    for r in rows:
        print_issue(r, cfg, skills, verbose=bool(args.issue))
    if args.issue:
        return 0

    open_numbers = {r["number"] for r in rows}
    pr_rows = prs(cfg)
    print(f"\n== open PRs: {len(pr_rows)}")
    for r in pr_rows:
        print_pr(r, open_numbers)

    # A PR that touches a file a candidate names may already cover it; say so once.
    print("\n== PR files that open candidates name")
    for pr in pr_rows:
        for r in rows:
            body = (r["body"] or "") + r["title"]
            named = [p for p in pr["paths"] if Path(p).name in body]
            if named and r["number"] not in pr["closes"]:
                print(f"   PR #{pr['number']} touches {', '.join(named)}; candidate #{r['number']} names it and is not in its Closes")
    return 0

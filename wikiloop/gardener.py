"""`wikiloop gardener`: re-verify skills whose sources changed since `last-verified`.

    wikiloop gardener                    # report: what may be stale and why
    wikiloop gardener --fix              # one agent session and one PR per stale skill
    wikiloop gardener --fix --skill NAME # only that skill
    wikiloop gardener --since 2026-08-01 # pretend every skill was verified then

A skill's `sources` are GitHub URLs (a repo, or a tree/blob path in it). Commits to those paths
after `last-verified` mean the skill may describe something that moved. Skills past
`lint.stale_days` are listed even without commits. `--fix` runs `claude -p` in a fresh git
worktree per skill: the session reads the commits, checks the skill sentence by sentence,
edits only what is now false, bumps `last-verified` and opens a PR for a person to review.
Needs `gh` and `claude`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path

GITHUB = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:/(?:tree|blob)/([^/]+)/(.+?))?/?$")
COMMITS_SHOWN = 5
SESSION_MAX_TURNS = 80
SESSION_TOOLS = "Read,Glob,Grep,Edit,Write,Skill,Bash(git *),Bash(gh *),Bash(python3 *)"

PROMPT = """\
You are re-verifying the wiki skill `{skill}` (owner {owner}, last verified {verified}).
Its sources have commits since that date, listed below. Read `CONTRIBUTING.md` first, then
`skills/{skill}/SKILL.md` and its `references/`.

{report}

Your job is to check that the skill does not lie, not to grow it. For each commit, read the
diff (`gh api repos/OWNER/REPO/commits/SHA` returns files with patches; `gh pr view` /
`gh pr diff` when the title names a PR). Then decide, sentence by sentence, whether the skill
still holds.

Edit the skill only when a sentence in it is now false, or a link or path it names no longer
exists. Fix that sentence; do not restructure. The expected outcome is that nothing but the
date moves.

Do not add facts from the diff. The wiki records mechanisms and traps that a reader cannot
see by looking at the live system; it never mirrors a file's current contents, thresholds,
table names, error codes or sizes. If the diff shows a mechanism-level trap that the skill
lacks, do not write it into the skill. Put it in the PR body under `Candidate:` in one or two
sentences, so a reviewer decides.

Set `last-verified` in `skills/{skill}/SKILL.md` to {today}, run `python3 {core}/bin/wikiloop build`
and `python3 {core}/bin/wikiloop lint`, and fix anything they report.

If `git status --short` is empty after that, there is nothing to record: do not commit, do
not open a PR. Reply with `holds: nothing to change`, one line per commit reviewed, and any
`Candidate:` lines.

Otherwise commit on the current branch with subject `wiki({skill}): re-verify against
sources`, or `wiki({skill}): <what was wrong>` if a sentence had to change. Body: one line
per commit reviewed, `sha: what it changed, whether the skill still holds`, then any
`Candidate:` lines. Push with `git push -u origin HEAD` and open a PR with
`gh pr create --fill`. Report the PR URL as your last line.
"""


def gh(*args: str) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"gh {' '.join(args)} failed")
    return proc.stdout


def read_skill(skill_dir: Path) -> dict:
    text = (skill_dir / "SKILL.md").read_text()
    end = text.find("\n---\n", 4)
    head = text[4:end].splitlines() if text.startswith("---\n") and end > 0 else []

    fields: dict = {"sources": []}
    in_sources = False
    for line in head:
        if line.startswith("sources:"):
            in_sources = True
            continue
        if in_sources and line.startswith("  - "):
            fields["sources"].append(line[4:].strip())
            continue

        in_sources = False
        m = re.match(r"^(owner|last-verified|generated):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def commits_since(url: str, since: date) -> list[dict] | None:
    """Commits that touch the source after `since`; None if the URL is not a GitHub repo path."""
    m = GITHUB.match(url)
    if not m:
        return None
    owner, repo, ref, path = m.groups()

    query = f"since={since.isoformat()}T00:00:00Z&per_page=100"
    if ref:
        query += f"&sha={ref}"
    if path:
        query += f"&path={path}"

    try:
        raw = gh("api", f"repos/{owner}/{repo}/commits?{query}")
    except RuntimeError as e:
        return [{"error": str(e)}]

    return [{"sha": c["sha"][:7], "date": c["commit"]["committer"]["date"][:10],
             "title": c["commit"]["message"].split("\n", 1)[0], "url": c["html_url"]}
            for c in json.loads(raw)]


def scan(root: Path, stale_days: int, since: date | None = None) -> list[dict]:
    """`since` overrides every skill's last-verified, e.g. after a bulk import."""
    findings = []
    for skill_dir in sorted(p for p in (root / "skills").iterdir() if p.is_dir()):
        fm = read_skill(skill_dir)
        if fm.get("generated"):
            continue  # the core's release verifies its own skills

        try:
            verified = since or datetime.strptime(fm.get("last-verified", ""), "%Y-%m-%d").date()
        except ValueError:
            continue

        age = (date.today() - verified).days
        changed = []
        for url in fm["sources"]:
            commits = commits_since(url, verified)
            if commits:
                changed.append({"url": url, "commits": commits})

        if changed or age > stale_days:
            findings.append({"skill": skill_dir.name, "owner": fm.get("owner", ""),
                             "verified": verified.isoformat(), "age": age, "changed": changed})
    return findings


def render(findings: list[dict], stale_days: int) -> str:
    if not findings:
        return "Nothing to re-verify: every skill's sources are unchanged since `last-verified`."

    out = []
    for f in findings:
        head = f"- `{f['skill']}` (owner {f['owner']}, verified {f['verified']}, {f['age']} days ago)"
        if not f["changed"]:
            out.append(f"{head}: older than {stale_days} days, no source commits")
            continue

        out.append(head)
        for src in f["changed"]:
            commits = src["commits"]
            if "error" in commits[0]:
                out.append(f"  - {src['url']}: unreachable ({commits[0]['error']})")
                continue

            out.append(f"  - {src['url']}: {len(commits)} commit(s)")
            for c in commits[:COMMITS_SHOWN]:
                out.append(f"    - [{c['sha']}]({c['url']}) {c['date']} {c['title']}")
            if len(commits) > COMMITS_SHOWN:
                out.append(f"    - … and {len(commits) - COMMITS_SHOWN} more")
    return "\n".join(out)


def fix(root: Path, cfg: dict, finding: dict) -> str:
    """Run one agent session in a fresh worktree; returns the session's last message."""
    skill = finding["skill"]
    branch = f"gardener/{skill}-{date.today().isoformat()}"
    worktree = Path(tempfile.mkdtemp(prefix=f"gardener-{skill}-"))

    subprocess.run(["git", "-C", str(root), "fetch", "-q", "origin", "main"], check=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-b", branch, str(worktree), "origin/main"],
                   check=True)

    prompt = PROMPT.format(skill=skill, owner=finding["owner"], verified=finding["verified"],
                           report=render([finding], cfg["lint"]["stale_days"]), today=date.today().isoformat(),
                           core=cfg["core"]["path"])
    try:
        proc = subprocess.run(
            ["claude", "-p", "--output-format", "json", "--max-turns", str(SESSION_MAX_TURNS),
             "--permission-mode", "acceptEdits", "--allowedTools", SESSION_TOOLS,
             "--plugin-dir", str(worktree), prompt],
            cwd=worktree, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return f"session failed: {proc.stderr.strip()[-500:]}"
        try:
            return json.loads(proc.stdout).get("result", "").strip()
        except ValueError:
            return proc.stdout.strip()[-500:]
    finally:
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)], capture_output=True)
        subprocess.run(["git", "-C", str(root), "branch", "-D", branch], capture_output=True)
        shutil.rmtree(worktree, ignore_errors=True)


def main(root: Path, cfg: dict, argv: list[str]) -> int:
    only = argv[argv.index("--skill") + 1] if "--skill" in argv else None
    since = date.fromisoformat(argv[argv.index("--since") + 1]) if "--since" in argv else None
    stale_days = cfg["lint"]["stale_days"]

    findings = scan(root, stale_days, since)
    if only:
        findings = [f for f in findings if f["skill"] == only]

    if "--fix" not in argv:
        print(render(findings, stale_days))
        return 0
    if not findings:
        print("nothing to re-verify")
        return 0

    for f in findings:
        print(f"== {f['skill']}", flush=True)
        print(fix(root, cfg, f) or "(no output)")
    return 0

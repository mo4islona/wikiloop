"""`wikiloop pr-lines`: print a wiki PR's full diff and review hints. No model call; the verdict
is the agent's.

    wikiloop pr-lines N                                   # PR N in the wiki repo
    git diff origin/main...HEAD | wikiloop pr-lines -

A hint marks where to look, not a verdict. Read the full diff, including deletions.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

CODE_EXT = r"rs|go|ts|tsx|js|mjs|sol|java|kt|cpp|py"
# The wiki's own tooling is named on purpose; product code is not.
OWN_TOOLING = re.compile(r"^(scripts|hooks|skills|core|extensions)/|/scripts/")
RUNTIME = re.compile(r"(?i)^(node|next|nuxt|vue|react|deno)\.js$")
CODE_PATH = re.compile(rf"(?<![\w/.-])([\w./-]*\w\.(?:{CODE_EXT}))(:\d+)?\b")
BACKTICKED = re.compile(r"`([^`\n]+)`")
IDENTIFIER = re.compile(r"::|\w\(\)$|^(fn|def|func|struct|impl|class|enum) |^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+$")
CONFIG_KEY = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
NOT_A_KEY = re.compile(r"\.(md|py|ya?ml|json|ts|rs|sh|toml|txt|js|go|sql|dev|com|io|net|org|xyz|app|cloud)$")
VALUE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|min|h|KB|MB|GB|KiB|MiB|GiB|Mi|Gi|Ti|Mbps|Gbps|%)(?![\w-])"
                   r"|\b0\.\d+\b|\bv\d+\.\d+(?:\.\d+)?\b|\bdefault(?:s)? (?:is |of )?\d")
REPLICAS = re.compile(r"\b\d+ replicas?\b|×\d+\b")
# "529s" counts responses, but "120s" is a timeout: only status codes are exempt.
HTTP_PLURAL = re.compile(r"(?:20[046]|30[124]|40[0134689]|41[03]|429|499|50[0234]|529)s")
STATE = re.compile(r"\b(now|currently|still|not yet|as of|recently|so far|temporarily)\b"
                   r"|\bsince ~?20\d\d-\d\d(?:-\d\d)?|\*\*Fix:\*\*\s*open\b|\(done \d", re.I)
DATE = re.compile(r"\b20\d\d-\d\d(?:-\d\d)?\b")
ENTRY_HEADER = re.compile(r"^## (20\d\d-\d\d-\d\d)\b", re.M)
SUPERSEDED = re.compile(r"\[superseded by 20\d\d-\d\d-\d\d\]")
FRONTMATTER_OK = re.compile(r"^\s*(last-verified:|- (https?://|\.\./))")


def hints(line: str, entry_dates: frozenset[str] = frozenset()) -> list[str]:
    if FRONTMATTER_OK.match(line):
        return []

    found = []
    for m in CODE_PATH.finditer(line):
        if not OWN_TOOLING.search(m.group(1)) and not RUNTIME.match(m.group(1)):
            found.append(f"code path: {m.group(0)}")
            if m.group(2):
                found.append(f"line number: {m.group(0)}")
    for m in BACKTICKED.finditer(line):
        token = m.group(1).strip()
        if IDENTIFIER.search(token):
            found.append(f"code identifier: {token}")
        elif CONFIG_KEY.match(token) and not NOT_A_KEY.search(token):
            found.append(f"config key: {token}")
    for m in VALUE.finditer(line):
        if not HTTP_PLURAL.fullmatch(m.group(0)):
            found.append(f"value: {m.group(0)}")
    for m in REPLICAS.finditer(line):
        found.append(f"replica count: {m.group(0)}")
    for m in STATE.finditer(line):
        found.append(f"state wording: {m.group(0)}")

    # A grep-first entry is named by its date, so a date that names one is a link.
    undated = SUPERSEDED.sub("", ENTRY_HEADER.sub("", line))
    for m in DATE.finditer(undated):
        if m.group(0) not in entry_dates:
            found.append(f"date outside an entry header: {m.group(0)}")
    return found


def added_lines(diff: str):
    """Yield (path, new line number, text) for every added line."""
    path, lineno = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            lineno = int(re.search(r"\+(\d+)", raw).group(1))
        elif path is None or raw.startswith("--- "):
            continue
        elif raw.startswith("+"):
            yield path, lineno, raw[1:]
            lineno += 1
        elif not raw.startswith("-"):
            lineno += 1


def entry_dates(skills: Path, diff: str) -> frozenset[str]:
    """Dates of grep-first entries in the checkout and among the diff's added lines."""
    dates = set()
    for path in skills.glob("**/*.md"):
        dates.update(ENTRY_HEADER.findall(path.read_text(encoding="utf-8")))

    for _, _, text in added_lines(diff):
        dates.update(ENTRY_HEADER.findall(text))
    return frozenset(dates)


def pr_header(repo: str, number: str) -> str:
    fields = "number,title,author,body,state,files,statusCheckRollup"
    pr = json.loads(subprocess.run(["gh", "pr", "view", number, "-R", repo, "--json", fields],
                                   capture_output=True, text=True, check=True).stdout)
    checks = sorted({c.get("conclusion") or c.get("state") or "PENDING" for c in pr["statusCheckRollup"]}) or ["none"]
    files = ", ".join(f"{f['path']} (+{f['additions']} -{f['deletions']})" for f in pr["files"])
    return (f"#{pr['number']} {pr['title']}  [{pr['state']}, {pr['author']['login']}, checks: {'/'.join(checks)}]\n"
            f"body: {(pr['body'] or '(empty)').strip()}\n"
            f"files: {files}\n")


def main(root: Path, repo: str, argv: list[str], stdin) -> int:
    if len(argv) != 1:
        print(__doc__.strip())
        return 2

    source = argv[0]
    if source == "-":
        diff = stdin.read()
    else:
        print(pr_header(repo, source))
        diff = subprocess.run(["gh", "pr", "diff", source, "-R", repo],
                              capture_output=True, text=True, check=True).stdout

    print("Full diff (including deletions and context):")
    print(diff, end="" if diff.endswith("\n") else "\n")
    print("\nHints for added lines (not verdicts):")

    entries = entry_dates(root / "skills", diff)
    for path, lineno, text in added_lines(diff):
        if path == "INDEX.md" or "/archive/" in path or not text.strip():
            continue

        found = hints(text, entries)
        if found:
            print(f"{path}:{lineno}")
            for hint in found:
                print(f"  ! {hint}")
    return 0

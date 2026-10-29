"""`wikiloop candidate`: search, file and comment on candidates, with the gate checked first.

    wikiloop candidate search '<keyword>'
    wikiloop candidate file -t '<symptom as a person would say it>' < body.md
    wikiloop candidate comment <number> < text.md

Runs in any session, on any python3: it reads the resolved config, not wikiloop.toml. A body
without a line that `[gate] required` names is refused before anything is sent. When the
tracker cannot be reached, the text goes to <cache>/candidates.md, so a finding is never lost
to a missing login.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from wikiloop.config import runtime_config
from wikiloop.inbox import InboxError, make_inbox

EXIT_REFUSED = 2


def missing_lines(body: str, cfg: dict) -> list[str]:
    keys = [r["key"] for r in cfg["gate"]["required"]]
    return [key for key in keys if not re.search(rf"^\W*{re.escape(key)}\W*:", body, re.IGNORECASE | re.MULTILINE)]


def cache_file(cfg: dict) -> Path:
    import os

    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / cfg["wiki"]["plugin"] / "candidates.md"


def keep_locally(cfg: dict, title: str, body: str, why: str) -> Path:
    path = cache_file(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with path.open("a") as f:
        f.write(f"\n## {stamp} — {title}\n\n{body.strip()}\n\n(not filed: {why})\n")
    return path


def read_body(args: argparse.Namespace) -> str:
    if args.body_file:
        return Path(args.body_file).read_text()
    return sys.stdin.read()


def search(cfg: dict, args: argparse.Namespace) -> int:
    rows = make_inbox(cfg).search(args.query)
    for row in rows:
        labels = ",".join(l["name"] for l in row.get("labels", []))
        print(f"#{row['number']}  {row['title']}  [{labels}]  {row['url']}")

    if not rows:
        print("no open candidate matches")
    return 0


def file(cfg: dict, args: argparse.Namespace) -> int:
    body = read_body(args)
    missing = missing_lines(body, cfg)
    if missing:
        help_lines = "\n".join(f"- {r['key']}: {r.get('help', '')}" for r in cfg["gate"]["required"] if r["key"] in missing)
        print(f"refused: the body lacks {', '.join(missing)}. Add one line each and file again:\n{help_lines}\n"
              "If you cannot write them, the fact is not wiki material: reply `wiki: nothing new`.")
        return EXIT_REFUSED

    try:
        url = make_inbox(cfg).file(args.title, body)
    except InboxError as e:
        path = keep_locally(cfg, args.title, body, str(e))
        print(f"NOT FILED ({e}); the text is kept in {path}. Tell the user.")
        return 0

    print(url)
    return 0


def comment(cfg: dict, args: argparse.Namespace) -> int:
    body = read_body(args)
    try:
        url = make_inbox(cfg).comment(args.number, body)
    except InboxError as e:
        path = keep_locally(cfg, f"comment on #{args.number}", body, str(e))
        print(f"NOT SENT ({e}); the text is kept in {path}. Tell the user.")
        return 0

    print(url)
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wikiloop candidate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="resolved config (hooks/wikiloop.json); found by default")
    sub = ap.add_subparsers(dest="action", required=True)

    s = sub.add_parser("search", help="open candidates that match a keyword")
    s.add_argument("query")

    f = sub.add_parser("file", help="file a candidate; the body on stdin or --body-file")
    f.add_argument("-t", "--title", required=True)
    f.add_argument("--body-file")

    c = sub.add_parser("comment", help="add to an open candidate; the text on stdin or --body-file")
    c.add_argument("number", type=int)
    c.add_argument("--body-file")

    args = ap.parse_args(argv)
    cfg = runtime_config(args.config)
    actions = {"search": search, "file": file, "comment": comment}
    return actions[args.action](cfg, args)

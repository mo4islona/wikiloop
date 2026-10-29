"""`wikiloop candidate`: search, file and comment on candidates, with the gate checked first.

    wikiloop candidate search '<keyword>'
    wikiloop candidate file -t '<symptom as a person would say it>' < body.md
    wikiloop candidate comment <number> < text.md
    wikiloop candidate send

Runs in any session, on any python3: it reads the resolved config, not wikiloop.toml. A body
without a line that `[gate] required` names is refused before anything is sent. When the
tracker cannot be reached, the text is queued in <cache>/candidates.md, so a finding is never
lost to a missing login or a sandbox without network; `send` files the queue later.
"""
from __future__ import annotations

import argparse
import fcntl
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from wikiloop.config import runtime_config
from wikiloop.inbox import InboxError, make_inbox

EXIT_REFUSED = 2
QUEUED = re.compile(r"^## (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) — (.+)$", re.MULTILINE)
COMMENT_TITLE = re.compile(r"comment on #(\d+)")
SEND = f"python3 {Path(__file__).resolve().parents[1] / 'bin' / 'wikiloop'} candidate send"


def missing_lines(body: str, cfg: dict) -> list[str]:
    keys = [r["key"] for r in cfg["gate"]["required"]]
    return [key for key in keys if not re.search(rf"^\W*{re.escape(key)}\W*:", body, re.IGNORECASE | re.MULTILINE)]


def cache_file(cfg: dict) -> Path:
    import os

    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / cfg["wiki"]["plugin"] / "candidates.md"


@contextmanager
def locked(path: Path):
    """The queue file, held against a parallel `send` that rewrites it.

    It is never deleted: a writer that waits for the lock would append to the unlinked file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield f


def keep_locally(cfg: dict, title: str, body: str, why: str) -> Path:
    path = cache_file(cfg)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with locked(path) as f:
        f.write(f"\n## {stamp} — {title}\n\n{body.strip()}\n\n(not filed: {why})\n")
    return path


def queued(text: str) -> tuple[str, list[tuple[str, str, str]]]:
    """The text before the first entry, and each entry as (raw text, title, body), oldest first."""
    heads = list(QUEUED.finditer(text))
    if not heads:
        return text, []

    ends = [head.start() for head in heads[1:]] + [len(text)]
    entries = []
    for head, end in zip(heads, ends):
        body = text[head.end():end].strip().rsplit("\n\n(not filed:", 1)[0]
        entries.append((text[head.start():end], head.group(2), body))
    return text[:heads[0].start()], entries


def read_body(args: argparse.Namespace) -> str:
    if args.body_file:
        return Path(args.body_file).read_text()
    return sys.stdin.read()


def search(cfg: dict, args: argparse.Namespace) -> int:
    try:
        rows = make_inbox(cfg).search(args.query)
    except InboxError as e:
        print(f"NOT SEARCHED ({e}); the open candidates are unknown. File anyway: triage merges duplicates.")
        return 1

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
        print(f"NOT FILED ({e}); queued in {path}. Tell the user: `{SEND}` files it once the tracker is reachable.")
        return 0

    print(url)
    return 0


def comment(cfg: dict, args: argparse.Namespace) -> int:
    body = read_body(args)
    try:
        url = make_inbox(cfg).comment(args.number, body)
    except InboxError as e:
        path = keep_locally(cfg, f"comment on #{args.number}", body, str(e))
        print(f"NOT SENT ({e}); queued in {path}. Tell the user: `{SEND}` sends it once the tracker is reachable.")
        return 0

    print(url)
    return 0


def deliver(cfg: dict, title: str, body: str) -> str:
    number = COMMENT_TITLE.fullmatch(title)
    if number:
        return make_inbox(cfg).comment(int(number.group(1)), body)
    return make_inbox(cfg).file(title, body)


def send(cfg: dict, args: argparse.Namespace) -> int:
    path = cache_file(cfg)
    if not path.exists():
        print("nothing queued")
        return 0

    with locked(path) as f:
        f.seek(0)
        before, entries = queued(f.read())
        if not entries:
            print("nothing queued")
            return 0

        unsent = []
        for raw, title, body in entries:
            try:
                print(deliver(cfg, title, body))
            except InboxError as e:
                unsent.append(raw)
                print(f"NOT SENT ({e}): {title}")

        # An interrupted run leaves the file as it was: a duplicate at triage, never a lost finding.
        if len(unsent) < len(entries):
            note = before if before.strip() else ""
            f.truncate(0)
            f.write(note + "".join(unsent))

    if unsent:
        print(f"{len(unsent)} of {len(entries)} still queued in {path}")
        return 1
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

    sub.add_parser("send", help="file the candidates and comments queued while the tracker was out of reach")

    args = ap.parse_args(argv)
    cfg = runtime_config(args.config)
    actions = {"search": search, "file": file, "comment": comment, "send": send}
    return actions[args.action](cfg, args)

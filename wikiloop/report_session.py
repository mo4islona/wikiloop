"""`wikiloop report-session <transcript.jsonl> "<what went wrong>" [--dry-run]`

Redacts secret-shaped strings in the transcript and in a note with the complaint, then
uploads both to the wiki's session-report bucket under <date>/<user>-<session>-<time>/. The bucket is write-only for the
uploader: it cannot list or read back, and the prefix carries the minute, so nothing is
overwritten. Prints the prefix. `--dry-run` redacts and reports, uploads nothing.
"""
from __future__ import annotations

import getpass
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from wikiloop import secret_scan
from wikiloop.config import runtime_config

UPLOADERS = {"gcs": ("gcloud", ["storage", "cp", "--no-user-output-enabled"]), "s3": ("aws", ["s3", "cp", "--quiet"])}


def redact(src: Path, dst: Path, extra: list) -> int:
    """The lint's scanner with a lower bar: a false hit costs a word in a replay, a miss leaks
    a credential. Replaced, not dropped, so the line structure a reader relies on survives."""
    count = 0
    with src.open(errors="replace") as fin, dst.open("w") as fout:
        for line, n in secret_scan.redact(fin, extra):
            fout.write(line)
            count += n
    return count


def timestamps(path: Path) -> tuple[str, str]:
    found = re.findall(r'"timestamp":"([^"]*)"', path.read_text(errors="ignore"))
    return (found[0], found[-1]) if found else ("?", "?")


def note(transcript: Path, complaint: str, redacted: int, user: str) -> str:
    first, last = timestamps(transcript)
    with transcript.open(errors="replace") as f:
        lines = sum(1 for _ in f)
    return (
        "# Session report\n\n"
        f"- reported: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} by {user}\n"
        f"- session: {transcript.stem} ({lines} records, {first} .. {last})\n"
        f"- plugin: {os.environ.get('CLAUDE_PLUGIN_ROOT', 'unknown')}\n"
        f"- redacted strings in the transcript: {redacted}\n\n"
        f"## What went wrong\n\n{complaint}\n"
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    transcript, complaint = Path(argv[0]), argv[1]
    dry_run = "--dry-run" in argv
    cfg = runtime_config()
    target = cfg["report_session"]

    if target["kind"] == "none":
        print("this wiki has no session-report bucket (`report_session.kind = none`)")
        return 1
    if not transcript.is_file():
        print(f"no such file: {transcript}")
        return 1

    tool, args = UPLOADERS[target["kind"]]
    if not dry_run and shutil.which(tool) is None:
        print(f"`{tool}` is not installed; the {target['kind']} bucket needs it")
        return 1

    user = re.sub(r"[^\w.-]", "-", getpass.getuser())
    stamp = time.strftime("%Y-%m-%dT%H%M", time.gmtime())
    prefix = f"{target['bucket'].rstrip('/')}/{stamp[:10]}/{user}-{transcript.stem}-{stamp[11:]}"

    extra = secret_scan.wiki_tokens(cfg)
    with tempfile.TemporaryDirectory() as work:
        redacted_path = Path(work) / "transcript.jsonl"
        count = redact(transcript, redacted_path, extra)

        # The complaint is the user's own text and may quote what the session printed.
        note_text, in_note = secret_scan.redact_text(note(transcript, complaint, count, user), extra)
        count += in_note
        note_path = Path(work) / "note.md"
        note_path.write_text(note_text)

        if dry_run:
            print(f"dry run: would upload to {prefix}/ ({count} strings redacted)\n")
            print(note_path.read_text())
            return 0

        for path in (redacted_path, note_path):
            proc = subprocess.run([tool, *args, str(path), f"{prefix}/{path.name}"], capture_output=True, text=True)
            if proc.returncode != 0:
                print(f"upload failed: {proc.stderr.strip()[-300:]}", file=sys.stderr)
                return 1

    print(f"uploaded: {prefix}/ (transcript.jsonl, note.md; {count} strings redacted; "
          f"expires in {target['ttl_days']} days)")
    return 0

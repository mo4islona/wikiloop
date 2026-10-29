"""Command dispatch. Maintainer commands read `wikiloop.toml` (Python 3.11+); the commands a
session runs read the resolved `hooks/wikiloop.json` and work on any python3."""
from __future__ import annotations

import sys
from pathlib import Path

from wikiloop.config import ConfigError, find_root, load

USAGE = """\
usage: wikiloop <command> [args]

in a wiki checkout (reads wikiloop.toml):
  build [--check] [--strict]   generate the plugin, skills and docs from config, guides and core
  lint [--stale]               enforce the contribution rules
  check                        the rails still hold with this config; the core is unmodified
  guides                       overrides and whether core changed the sections they replace
  inbox [--new|--issue N]      dump candidates and PRs for a triage pass
  pr-lines N|-                 a PR's full diff with review hints
  shepherd [--json]            the next actions for one shepherd pass
  apply pairs.json             apply exact OLD -> NEW pairs
  evals [--case GLOB]          trigger evals: do descriptions catch real prompts
  gardener [--fix]             skills whose sources changed since last-verified
  update [REF] [--from SRC]    replace the vendored core with a release

in any session (reads hooks/wikiloop.json):
  candidate search|file|comment|send   the inbox, with the gate checked first
  report-session FILE "WHAT"      upload a bad session for the maintainers
  session-summary FILE            where a session spent its time and tokens

anywhere:
  init DIR --plugin --company --domain --repo   start a wiki for a new company
  version
"""

WIKI_COMMANDS = {"build", "lint", "check", "guides", "inbox", "pr-lines", "shepherd", "evals", "gardener", "update"}


def wiki_command(command: str, args: list[str]) -> int:
    root = find_root(Path.cwd())
    cfg = load(root)

    if command == "build":
        from wikiloop import build
        return build.main(root, cfg, args)
    if command == "lint":
        from wikiloop import lint
        return lint.main(root, cfg, args)
    if command == "check":
        from wikiloop import check
        return check.main(root, cfg, args)
    if command == "guides":
        return guides_status(root)
    if command == "inbox":
        from wikiloop import triage
        return triage.main(root, cfg, args)
    if command == "pr-lines":
        from wikiloop import pr_lines
        return pr_lines.main(root, cfg["wiki"]["repo"], args, sys.stdin)
    if command == "shepherd":
        from wikiloop import shepherd
        return shepherd.main(cfg, args)
    if command == "evals":
        from wikiloop import evals
        return evals.main(root, cfg, args)
    if command == "gardener":
        from wikiloop import gardener
        return gardener.main(root, cfg, args)

    from wikiloop import update
    return update.main(root, cfg, args)


def guides_status(root: Path) -> int:
    from wikiloop.render import Guides, split_sections

    guides = Guides(root)
    overrides = sorted((root / "guides").glob("*.md"))
    for path in overrides:
        if path.stem not in guides.names():
            continue
        for sid, attrs, _ in split_sections(path.read_text(), f"guides/{path.name}"):
            print(f"guides/{path.name}#{sid}: {attrs.get('mode', 'replace')}")
        guides.sections(path.stem)

    for w in guides.warnings:
        print(f"\nWARN {w}")
    if not overrides:
        print("no overrides: every guide is the core's")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(USAGE)
        return 0

    command, args = argv[0], argv[1:]
    try:
        if command in WIKI_COMMANDS:
            return wiki_command(command, args)
        if command == "candidate":
            from wikiloop import candidate
            return candidate.main(args)
        if command == "report-session":
            from wikiloop import report_session
            return report_session.main(args)
        if command == "session-summary":
            from wikiloop import session_summary
            return session_summary.main(args)
        if command == "apply":
            from wikiloop import shepherd
            return shepherd.apply(args)
        if command == "init":
            from wikiloop import init
            return init.main(args)
        if command == "version":
            from wikiloop.config import CORE
            print((CORE / "VERSION").read_text().split()[0])
            return 0
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2

    print(f"unknown command `{command}`\n\n{USAGE}")
    return 2

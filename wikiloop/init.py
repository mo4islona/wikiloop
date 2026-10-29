"""`wikiloop init <dir> --plugin NAME --company NAME --domain TEXT --repo OWNER/NAME`

Start a wiki for a new company: copy the skeleton (config, two empty maps, an eval case, CI),
vendor this core into `<dir>/core`, and run the first build. The maps come first on purpose:
without content the session rule has nothing to point at, and the loop never starts.
"""
from __future__ import annotations

import argparse
import string
import subprocess
import sys
from datetime import date
from pathlib import Path

from wikiloop import vendor
from wikiloop.config import CONFIG_NAME, CORE, PLUGIN_NAME, REPO_NAME

SKELETON = CORE / "template"


def core_commit() -> str:
    proc = subprocess.run(["git", "-C", str(CORE), "rev-parse", "HEAD"], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def copy_skeleton(target: Path, values: dict) -> list[str]:
    written = []
    for src in sorted(p for p in SKELETON.rglob("*") if p.is_file() and p.name != ".DS_Store"):
        rel = src.relative_to(SKELETON)
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(string.Template(src.read_text()).safe_substitute(values))
        written.append(rel.as_posix())
    return written


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wikiloop init", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir")
    ap.add_argument("--plugin", required=True, help="plugin name, e.g. acme-wiki")
    ap.add_argument("--company", required=True, help="company name, e.g. ACME")
    ap.add_argument("--domain", required=True, help='what the wiki maps, e.g. "ACME systems"')
    ap.add_argument("--repo", required=True, help="where the wiki repo lives, e.g. acme/ai-wiki")
    args = ap.parse_args(argv)

    if not PLUGIN_NAME.match(args.plugin) or not REPO_NAME.match(args.repo):
        print("--plugin is lowercase letters, digits and hyphens; --repo is <owner>/<name>")
        return 2

    target = Path(args.dir).resolve()
    if (target / CONFIG_NAME).exists():
        print(f"{target} already has a {CONFIG_NAME}")
        return 1

    values = {"plugin": args.plugin, "company": args.company, "domain": args.domain, "repo": args.repo,
              "today": date.today().isoformat()}
    written = copy_skeleton(target, values)

    core = target / "core"
    vendor.copy_tree(CORE, core)
    version = (CORE / "VERSION").read_text().split()[0]
    vendor.write_record(core, {"version": version, "ref": "init", "commit": core_commit(), "patches": []})

    built = subprocess.run([sys.executable, str(core / "bin" / "wikiloop"), "build"], cwd=target)
    if built.returncode != 0:
        return built.returncode

    print(f"\n{target}: {len(written)} skeleton files, core {version} in core/.")
    print("Next: fill skills/map-infra and skills/map-product, add a debug skill for the system "
          "people ask about most, then commit and push. Install from the checkout with:\n"
          "  ./install.sh --agents claude,codex")
    return 0

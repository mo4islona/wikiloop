"""`wikiloop update [<ref>] [--from <path or git url>]`: replace the vendored core with a release.

    wikiloop update              # the latest tag of `core.repo`
    wikiloop update v0.2.0
    wikiloop update --from ../wikiloop    # a local checkout, for core development

Steps: fetch the ref, replace `core/` whole, apply `core-patches/*.diff`, run the config
migrations between the two versions, rebuild, run `wikiloop check`. The result is a diff for
one PR: the person reviews the CHANGELOG lines and the regenerated files, CI runs the rest.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from wikiloop import vendor
from wikiloop.config import CONFIG_NAME

SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def version_key(ref: str) -> tuple[int, int, int]:
    m = SEMVER.match(ref)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def latest_tag(url: str) -> str:
    out = subprocess.run(["git", "ls-remote", "--tags", "--refs", url], capture_output=True, text=True, check=True).stdout
    tags = [line.rsplit("/", 1)[-1] for line in out.splitlines()]
    releases = sorted((t for t in tags if SEMVER.match(t)), key=version_key)
    if not releases:
        raise SystemExit(f"no release tags in {url}")
    return releases[-1]


def fetch(source: str, ref: str | None, into: Path) -> tuple[str, str]:
    """Clone `source` at `ref` into `into`; returns (ref, commit)."""
    is_local = Path(source).is_dir()
    if not is_local:
        ref = ref or latest_tag(source)

    clone = ["git", "clone", "-q", "--depth", "1", *(["--branch", ref] if ref else []), source, str(into)]
    if is_local:
        clone = ["git", "clone", "-q", "--no-local", source, str(into)]
    subprocess.run(clone, check=True)

    if is_local and ref:
        subprocess.run(["git", "-C", str(into), "checkout", "-q", ref], check=True)
    commit = subprocess.run(["git", "-C", str(into), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    return ref or "HEAD", commit


def migrate(root: Path, core: Path, old: str, new: str) -> list[str]:
    """Run core/migrations/<version>.py for each version in (old, new]; each rewrites the TOML text."""
    import importlib.util

    ran = []
    path = root / CONFIG_NAME
    for script in sorted((core / "migrations").glob("*.py"), key=lambda p: version_key(p.stem)):
        is_due = version_key(old) < version_key(script.stem) <= version_key(new)
        if not is_due:
            continue

        spec = importlib.util.spec_from_file_location(f"wikiloop_migration_{script.stem}", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        path.write_text(module.migrate(path.read_text()))
        ran.append(script.stem)
    return ran


def main(root: Path, cfg: dict, argv: list[str]) -> int:
    source = argv[argv.index("--from") + 1] if "--from" in argv else f"https://github.com/{cfg['core']['repo']}.git"
    positional = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--from")]
    ref = positional[0] if positional else None

    core_rel = cfg["core"]["path"]
    core = (root / core_rel).resolve()
    if core_rel.startswith(".."):
        print(f"core is at {core_rel}, outside this wiki: update the checkout itself, not a vendored copy")
        return 1

    old_version = cfg["core"]["version"]
    with tempfile.TemporaryDirectory(prefix="wikiloop-core-") as tmp:
        fetched = Path(tmp) / "core"
        ref, commit = fetch(source, ref, fetched)
        new_version = (fetched / "VERSION").read_text().split()[0]
        vendor.copy_tree(fetched, core)

    patches = vendor.apply_patches(root, core_rel)
    vendor.write_record(core, {"version": new_version, "ref": ref, "commit": commit, "patches": patches})
    migrations = migrate(root, core, old_version, new_version)

    print(f"core {old_version} -> {new_version} ({ref}, {commit[:7]})")
    if patches:
        print(f"patches applied: {', '.join(patches)}")
    if migrations:
        print(f"config migrations: {', '.join(migrations)}; review {CONFIG_NAME}")

    # The new core builds and checks itself: this process still runs the old one.
    cli = [sys.executable, str(core / "bin" / "wikiloop")]
    for command in ("build", "check"):
        if subprocess.run([*cli, command], cwd=root).returncode != 0:
            print(f"`wikiloop {command}` failed on the new core; fix it before the PR")
            return 1

    print(f"\nnext: read {core_rel}/CHANGELOG.md for {old_version} -> {new_version}, then open one PR with the diff")
    return 0

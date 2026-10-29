"""The vendored core: a copy of wikiloop inside a wiki repo, pinned and checked for local edits.

`core/.wikiloop-core.json` records what was copied (version, ref, commit), the patches applied
from `core-patches/`, and a hash of the tree after them. `wikiloop check` recomputes the hash:
a core edited by hand fails, because the next `wikiloop update` would silently drop the edit.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

RECORD = ".wikiloop-core.json"
# What a wiki needs from the core at run and build time; the rest is the core's own development.
EXCLUDED = {".git", ".github", "example", "tests", "__pycache__", ".DS_Store", RECORD}


def files(core: Path) -> list[Path]:
    out = []
    for path in sorted(core.rglob("*")):
        rel = path.relative_to(core)
        if path.is_file() and not EXCLUDED.intersection(rel.parts):
            out.append(rel)
    return out


def tree_hash(core: Path) -> str:
    digest = hashlib.sha256()
    for rel in files(core):
        digest.update(rel.as_posix().encode() + b"\0")
        digest.update((core / rel).read_bytes() + b"\0")
    return digest.hexdigest()[:16]


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)

    for rel in files(src):
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, target)


def apply_patches(root: Path, core_rel: str) -> list[str]:
    applied = []
    for patch in sorted((root / "core-patches").glob("*.diff")):
        already = subprocess.run(["git", "apply", "--reverse", "--check", f"--directory={core_rel}", str(patch)],
                                 cwd=root, capture_output=True)
        if already.returncode == 0:
            print(f"core-patches/{patch.name}: already in this core; delete the file")
            continue

        subprocess.run(["git", "apply", f"--directory={core_rel}", str(patch)], cwd=root, check=True)
        applied.append(patch.name)
    return applied


def write_record(core: Path, info: dict) -> None:
    record = {**info, "tree_hash": tree_hash(core)}
    (core / RECORD).write_text(json.dumps(record, indent=2) + "\n")


def read_record(core: Path) -> dict | None:
    try:
        return json.loads((core / RECORD).read_text())
    except (OSError, ValueError):
        return None

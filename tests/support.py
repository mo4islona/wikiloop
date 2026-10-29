"""Shared fixtures: the ACME example's resolved config, built fresh for each test run."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "example"
HOOKS = REPO / "hooks"
CLI = REPO / "bin" / "wikiloop"

sys.path.insert(0, str(REPO))

from wikiloop import build  # noqa: E402
from wikiloop.config import load  # noqa: E402


def resolved_config(overrides: dict | None = None) -> Path:
    """The example's hooks/wikiloop.json, written to a temp plugin root, with `overrides` merged per section."""
    cfg = load(EXAMPLE)
    for section, values in (overrides or {}).items():
        cfg[section].update(values)

    files, _ = build.generate(EXAMPLE, cfg)
    root = Path(tempfile.mkdtemp(prefix="wikiloop-test-"))
    path = root / "hooks" / "wikiloop.json"
    path.parent.mkdir(parents=True)
    path.write_text(files["hooks/wikiloop.json"])
    return path


def read(path: Path) -> dict:
    return json.loads(path.read_text())

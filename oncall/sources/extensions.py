"""Python modules a wiki supplies, loaded by path from its root.

A source extension (`[oncall] extensions`) exposes `collect(ctx) -> list` and builds each signal
with `ctx.signal(...)`; `ctx.query(expr)` runs PromQL against `[oncall.prometheus]`. It is a
source of its own, named `ext:<file stem>`: when it fails, its problems freeze like any other
source's. A presenter (`[oncall] presenter`) exposes `present(problem, view) -> dict`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def load(root: Path, path: str):
    full = (root / path).resolve()
    spec = importlib.util.spec_from_file_location(f"wikiloop_ext_{full.stem}", full)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {full}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_name(path: str) -> str:
    return f"ext:{Path(path).stem}"

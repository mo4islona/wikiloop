"""Load a wiki's `wikiloop.toml`, merge the defaults, validate.

`wikiloop build` writes the resolved config to `hooks/wikiloop.json` in the wiki. Hooks and the
commands a session runs (`candidate`, `report-session`) read that JSON, never the TOML: they run
on whatever `python3` a laptop has, and `tomllib` needs 3.11.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

CONFIG_NAME = "wikiloop.toml"
RESOLVED_PATH = "hooks/wikiloop.json"
CORE = Path(__file__).resolve().parent.parent
SCHEMA = 1

PLUGIN_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
REPO_NAME = re.compile(r"^[\w.-]+/[\w.-]+$")
SEVERITY = re.compile(r"^[a-z][a-z0-9-]*$")

DEFAULTS: dict = {
    "schema": SCHEMA,
    "wiki": {
        "plugin": "",
        "domain": "",
        "company": "",
        "description": "",
        "owner": "",
        "repo": "",
    },
    "inbox": {
        "kind": "github",
        "repo": "",
        "label": "candidate",
    },
    "gate": {
        "required": [
            {"key": "Why the wiki",
             "help": "where an agent would look first, and why it would not find the fact there"},
            {"key": "Not repo or vendor",
             "help": "which repo and which vendor docs you checked, and why neither is the fact's home"},
        ],
    },
    "investigation": {
        "debug_skills": ["debug-*"],
        "commands": ["kubectl"],
        "patterns": [],
        "mcp_tools": [],
        "threshold": 5,
        "reask": 20,
    },
    "skills": {
        "groups": [
            {"prefix": "map-", "title": "Maps: what exists and where"},
            {"prefix": "debug-", "title": "Debugging: localize a class of problem"},
            {"prefix": "howto-", "title": "Procedures"},
            {"prefix": "wiki-", "title": "About the wiki"},
        ],
        "vendor_examples": "Kubernetes, Docker, BigQuery",
    },
    "lint": {
        "description_max": 250,
        "skill_md_max_lines": 150,
        "reference_max_bytes": 12_000,
        "grep_first_max_bytes": 32_000,
        "grep_first_entry_max_chars": 1_500,
        "stale_days": 90,
        "required_fields": ["name", "description", "owner", "last-verified"],
        "english_only": True,
        "allowed_home_paths": [],
    },
    "report_session": {
        "kind": "none",
        "bucket": "",
        "ttl_days": 30,
    },
    "shepherd": {
        "max_rounds": 2,
        "max_land_prs": 2,
    },
    "evals": {
        "model": "",
        "threshold": 0.66,
        "runs": 3,
    },
    "install": {
        "access_hint": "ask a maintainer of the wiki for access",
        "checks": [],
    },
    "core": {
        "repo": "mo4islona/wikiloop",
    },
    "oncall": {
        "enabled": False,
    },
}

# Tables whose keys a wiki may extend: their content is checked by the code that reads them.
OPEN_TABLES = {"oncall"}


class ConfigError(Exception):
    pass


def find_root(start: Path) -> Path:
    """The nearest directory at or above `start` that holds a wikiloop.toml."""
    for directory in [start, *start.parents]:
        if (directory / CONFIG_NAME).is_file():
            return directory

    raise ConfigError(f"no {CONFIG_NAME} in {start} or above; run `wikiloop init` first")


def load(root: Path) -> dict:
    import tomllib

    try:
        raw = tomllib.loads((root / CONFIG_NAME).read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{CONFIG_NAME}: {e}") from None

    errors = unknown_keys(raw, DEFAULTS, "")
    cfg = merge(DEFAULTS, raw)
    cfg["oncall"] = merge(oncall_defaults(), cfg["oncall"])
    derive(cfg, root)
    errors += validate(cfg)

    if errors:
        raise ConfigError("\n".join(f"{CONFIG_NAME}: {e}" for e in errors))
    return cfg


def load_resolved(plugin_root: Path) -> dict:
    """What a hook or a session command reads: the JSON the last build wrote."""
    return json.loads((plugin_root / RESOLVED_PATH).read_text())


def runtime_config(explicit: str | None = None) -> dict:
    """The resolved config for a command a session runs: --config, the plugin root, the parent
    of a vendored core, or the nearest one above the working directory."""
    import os

    if explicit:
        return json.loads(Path(explicit).read_text())

    candidates = []
    if os.environ.get("CLAUDE_PLUGIN_ROOT"):
        candidates.append(Path(os.environ["CLAUDE_PLUGIN_ROOT"]))
    candidates.append(CORE.parent)
    cwd = Path.cwd()
    candidates += [cwd, *cwd.parents]

    for root in candidates:
        if (root / RESOLVED_PATH).is_file():
            return load_resolved(root)
    raise ConfigError(f"no {RESOLVED_PATH} found; run `wikiloop build` in the wiki, or pass --config")


def oncall_defaults() -> dict:
    try:
        from oncall.defaults import DEFAULTS as ONCALL
    except ImportError:
        return {"enabled": False}

    return copy.deepcopy(ONCALL)


def merge(base: dict, override: dict) -> dict:
    """Tables merge key by key; any other value, lists included, replaces the default."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        is_table = isinstance(value, dict) and isinstance(out.get(key), dict)
        out[key] = merge(out[key], value) if is_table else copy.deepcopy(value)
    return out


def unknown_keys(raw: dict, defaults: dict, prefix: str) -> list[str]:
    errors = []
    for key, value in raw.items():
        path = f"{prefix}{key}"
        if key not in defaults:
            errors.append(f"unknown key `{path}`")
            continue

        is_closed_table = isinstance(value, dict) and isinstance(defaults[key], dict) and key not in OPEN_TABLES
        if is_closed_table:
            errors += unknown_keys(value, defaults[key], f"{path}.")
    return errors


def derive(cfg: dict, root: Path) -> None:
    wiki = cfg["wiki"]
    wiki["description"] = wiki["description"] or (
        f"Self-learning knowledge base for {wiki['domain']}: agents read it before acting and file what they learn.")
    wiki["owner"] = wiki["owner"] or wiki["company"]
    cfg["inbox"]["repo"] = cfg["inbox"]["repo"] or wiki["repo"]

    # The gate's lines in the shapes the guides quote them.
    required = [r for r in cfg["gate"]["required"] if r.get("key")]
    gate = cfg["gate"]
    gate["keys"] = " / ".join(r["key"] for r in required)
    gate["lines"] = "\n".join(f"{r['key']}: ..." for r in required)
    gate["help"] = "\n".join(f"- {r['key']}: {r.get('help', '')}" for r in required)
    gate["inline_help"] = " ".join(f"{r['key']}: {r.get('help', '')}." for r in required)

    version, released = (CORE / "VERSION").read_text().split()[:2]
    cfg["core"]["version"] = version
    cfg["core"]["released"] = released
    cfg["core"]["path"] = relative(CORE, root)


def relative(path: Path, root: Path) -> str:
    """`path` as the wiki names it: `core` for a vendored copy, `..` for this repo's example."""
    import os

    return os.path.relpath(path.resolve(), root.resolve())


def validate(cfg: dict) -> list[str]:
    errors = []
    wiki = cfg["wiki"]

    if not PLUGIN_NAME.match(wiki["plugin"]):
        errors.append("`wiki.plugin` must be lowercase letters, digits and hyphens, at most 64")
    for key in ("domain", "company"):
        if not wiki[key].strip():
            errors.append(f"`wiki.{key}` is empty")
    if not REPO_NAME.match(wiki["repo"]):
        errors.append("`wiki.repo` must be `<owner>/<name>`")

    if cfg["inbox"]["kind"] != "github":
        errors.append(f"`inbox.kind` {cfg['inbox']['kind']!r} has no adapter; this version has `github`")
    if not REPO_NAME.match(cfg["inbox"]["repo"]):
        errors.append("`inbox.repo` must be `<owner>/<name>`")

    # The rails: a wiki tunes them, it cannot switch them off.
    required = cfg["gate"]["required"]
    if not required or not all(r.get("key", "").strip() for r in required):
        errors.append("`gate.required` needs at least one line, each with a `key`")

    investigation = cfg["investigation"]
    if investigation["threshold"] < 1:
        errors.append("`investigation.threshold` must be 1 or more")
    if investigation["reask"] < investigation["threshold"]:
        errors.append("`investigation.reask` must not be below `investigation.threshold`")
    has_signal = any(investigation[k] for k in ("debug_skills", "commands", "patterns", "mcp_tools"))
    if not has_signal:
        errors.append("`investigation` names no signal: the Stop hook could never ask")
    for pattern in investigation["patterns"]:
        try:
            re.compile(pattern)
        except re.error as e:
            errors.append(f"`investigation.patterns` {pattern!r}: {e}")

    if cfg["report_session"]["kind"] not in ("none", "gcs", "s3"):
        errors.append("`report_session.kind` must be `none`, `gcs` or `s3`")
    if cfg["report_session"]["kind"] != "none" and not cfg["report_session"]["bucket"]:
        errors.append("`report_session.bucket` is empty")

    for check in cfg["install"]["checks"]:
        if check.get("tier", "recommended") not in ("recommended", "optional"):
            errors.append("`install.checks` tier must be `recommended` or `optional`")
        if not check.get("name") or not check.get("check"):
            errors.append("each `install.checks` entry needs `name` and `check`")

    for group in cfg["skills"]["groups"]:
        if not group.get("prefix") or not group.get("title"):
            errors.append("each `skills.groups` entry needs `prefix` and `title`")

    if cfg["oncall"].get("enabled"):
        try:
            from oncall.defaults import validate as validate_oncall
        except ImportError:
            errors.append("`oncall.enabled` is true, but this core has no on-call engine")
        else:
            errors += validate_oncall(cfg)
    return errors

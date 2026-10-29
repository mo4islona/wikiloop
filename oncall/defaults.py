"""The `[oncall]` table: its defaults and its validation.

config.py merges DEFAULTS under a wiki's `[oncall]` (tables key by key, lists replaced whole)
and calls `validate` when `enabled` is true. The defaults reproduce the layout the engine was
built with: four severities, a pane of Major, Minor, Resolved and Chronic sections.
"""
from __future__ import annotations

import re

SEVERITY_SPEC_HELP = "a severity name, or a table of tier -> severity with a `default`"

SECTION_DEFAULTS: dict = {
    "title": "",
    "status": "open",
    "min_severity": "",
    "max_severity": "",
    "chronic": "any",
    "new": "any",
    "style": "full",
    "color": "",
    "limit": 0,
    "empty": "",
    "fold_below": False,
}

PROBE_DEFAULTS: dict = {
    "name": "",
    "description": "",
    "query": "",
    "component": "",
    "severity": "minor",
    "summary": "",
}

DEFAULTS: dict = {
    "enabled": False,
    "command": "oncall",
    "title": "On-call",
    "interval": 300,
    "resolve_after": 2,
    "heartbeat": 3600,
    "state_dir": "",
    # highest first; `color` is a terminal theme color name, "" draws dim
    "severities": [
        {"name": "critical", "color": "error"},
        {"name": "major", "color": "warning"},
        {"name": "minor", "color": "suggestion"},
        {"name": "info", "color": ""},
    ],
    # `loud` and above page a person; below `floor` nothing is NEW, counted on the line or streamed
    "loud": "major",
    "floor": "minor",
    "tiers": [],
    "thresholds": {
        "new_window": 7200,
        "chronic_after": 86400,
        "resolved_kept": 21600,
        "flap_quiet": 3600,
        "spread_every": 3600,
        "source_down_after": 2,
        "fleet_min": 5,
        "fleet_gap": 3600,
        "stale_slack": 120,
        "off_after": 3600,
        "start_guard": 600,
    },
    "subject": {
        "labels": ["service"],
        "noun": "subjects",
        "aliases": {},
        "place_labels": ["namespace", "service", "job"],
        "ignore_places": [],
        "component_label": "component",
        "component_prefixes": {},
        "component_aliases": {},
        "variant_label": "",
        "split_components": [],
        "tier_label": "tier",
        "tier_of": {},
        "env_label": "env",
        "env_of": {},
        "default_env": "prod",
        "no_fleet": [],
    },
    "alertmanager": {
        "url": "",
        "token_file": "",
        "token_env": "",
        "severity_label": "severity",
        "severity_map": {},
        "link_annotation": "",
        "link_label": "dashboard",
    },
    "prometheus": {
        "url": "",
        "token_file": "",
        "token_env": "",
    },
    "probes": [],
    "restarts": {
        "enabled": False,
        "window": "30m",
        "crash_loop_after": 3,
        "exclude_namespaces": "",
        "cluster_label": "cluster",
        "kube_contexts": {},
        "node_min": 3,
        "severity": {"crash-loop": "minor", "oom-killed": "info", "restarted": "info"},
    },
    "extensions": [],
    "presenter": "",
    "present": {
        "strip_prefixes": [],
    },
    "routes": {
        "team_label": "team",
        "teams": {},
        "channel": "",
        "severity_names": {},
        "url": "",
        "channel_ids": {},
    },
    "sections": [
        {**SECTION_DEFAULTS, "title": "Major, still open", "min_severity": "major",
         "color": "warning", "empty": "none"},
        {**SECTION_DEFAULTS, "title": "Minor, still open", "min_severity": "minor",
         "max_severity": "minor", "chronic": "exclude"},
        {**SECTION_DEFAULTS, "title": "Resolved, last {resolved_kept}", "status": "resolved",
         "min_severity": "minor", "style": "compact", "color": "success", "fold_below": True},
        {**SECTION_DEFAULTS, "title": "Chronic, no change", "min_severity": "minor",
         "max_severity": "minor", "chronic": "only", "style": "inline"},
    ],
}

# Tables whose keys the defaults list in full; others (aliases, kube_contexts, ...) are maps.
CLOSED = {
    "": DEFAULTS,
    "thresholds": DEFAULTS["thresholds"],
    "subject": DEFAULTS["subject"],
    "alertmanager": DEFAULTS["alertmanager"],
    "prometheus": DEFAULTS["prometheus"],
    "restarts": DEFAULTS["restarts"],
    "present": DEFAULTS["present"],
    "routes": DEFAULTS["routes"],
}

COMMAND = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
NAME = re.compile(r"^[a-z][a-z0-9-]*$")
WINDOW = re.compile(r"^\d+[smhd]$")
CHOICES = {
    "status": ("open", "resolved"),
    "chronic": ("any", "only", "exclude"),
    "new": ("any", "only", "exclude"),
    "style": ("full", "compact", "inline"),
}


def sections(oncall: dict) -> list[dict]:
    """Each configured section with every key filled."""
    return [{**SECTION_DEFAULTS, **s} for s in oncall["sections"]]


def probes(oncall: dict) -> list[dict]:
    return [{**PROBE_DEFAULTS, **p} for p in oncall["probes"]]


def validate(cfg: dict) -> list[str]:
    oncall = cfg["oncall"]
    errors = unknown(oncall)

    if not COMMAND.match(str(oncall["command"])):
        errors.append("`oncall.command` must be lowercase letters, digits and hyphens")

    # The rails: a wiki tunes the cycle, it cannot make a problem resolve without being absent.
    if not isinstance(oncall["resolve_after"], int) or oncall["resolve_after"] < 1:
        errors.append("`oncall.resolve_after` must be 1 or more: a problem resolves only after it was absent")
    if not isinstance(oncall["interval"], int) or oncall["interval"] < 30:
        errors.append("`oncall.interval` must be 30 seconds or more")
    for key, value in oncall["thresholds"].items():
        if not isinstance(value, int) or value < 1:
            errors.append(f"`oncall.thresholds.{key}` must be a positive integer")

    state_dir = oncall["state_dir"]
    if state_dir and not state_dir.startswith(("~/", "/")):
        errors.append("`oncall.state_dir` must start with `~/` or `/`: the watcher and the screen must find one place")

    names = [s.get("name", "") for s in oncall["severities"]]
    if not names or not all(NAME.match(n) for n in names) or len(set(names)) != len(names):
        errors.append("`oncall.severities` needs unique lowercase names, highest first")
        return errors

    for key in ("loud", "floor"):
        if oncall[key] not in names:
            errors.append(f"`oncall.{key}` {oncall[key]!r} is not one of `oncall.severities`")
    if not errors and names.index(oncall["floor"]) < names.index(oncall["loud"]):
        errors.append("`oncall.floor` must not be above `oncall.loud`")

    tiers = oncall["tiers"]
    if len(set(tiers)) != len(tiers) or not all(isinstance(t, str) and NAME.match(t) for t in tiers):
        errors.append("`oncall.tiers` needs unique lowercase names, highest first")
    for tier in oncall["subject"]["tier_of"]:
        if tier not in tiers:
            errors.append(f"`oncall.subject.tier_of` names tier {tier!r}, which `oncall.tiers` lacks")

    errors += severity_errors(oncall, names, tiers)
    errors += source_errors(oncall)
    errors += section_errors(oncall, names)
    return errors


def unknown(oncall: dict) -> list[str]:
    errors = []
    for table, known in CLOSED.items():
        value = oncall.get(table, {}) if table else oncall
        prefix = f"oncall.{table}." if table else "oncall."
        errors += [f"unknown key `{prefix}{key}`" for key in value if key not in known]

    for n, probe in enumerate(oncall["probes"]):
        errors += [f"unknown key `oncall.probes[{n}].{key}`" for key in probe if key not in PROBE_DEFAULTS]
    for n, section in enumerate(oncall["sections"]):
        errors += [f"unknown key `oncall.sections[{n}].{key}`" for key in section if key not in SECTION_DEFAULTS]
    return errors


def severity_errors(oncall: dict, names: list[str], tiers: list[str]) -> list[str]:
    errors = []
    specs = [(f"oncall.probes[{n}].severity", p["severity"]) for n, p in enumerate(probes(oncall))]
    specs += [(f"oncall.restarts.severity.{kind}", spec) for kind, spec in oncall["restarts"]["severity"].items()]

    for where, spec in specs:
        if isinstance(spec, str):
            if spec not in names:
                errors.append(f"`{where}` {spec!r} is not one of `oncall.severities`")
            continue

        if not isinstance(spec, dict) or "default" not in spec:
            errors.append(f"`{where}` must be {SEVERITY_SPEC_HELP}")
            continue
        for tier, severity in spec.items():
            if tier != "default" and tier not in tiers:
                errors.append(f"`{where}` names tier {tier!r}, which `oncall.tiers` lacks")
            if severity not in names:
                errors.append(f"`{where}.{tier}` {severity!r} is not one of `oncall.severities`")

    for value, severity in oncall["alertmanager"]["severity_map"].items():
        if severity not in names:
            errors.append(f"`oncall.alertmanager.severity_map.{value}` {severity!r} is not one of `oncall.severities`")
    return errors


def source_errors(oncall: dict) -> list[str]:
    errors = []
    has_source = any((oncall["alertmanager"]["url"], oncall["probes"], oncall["restarts"]["enabled"],
                      oncall["extensions"]))
    if not has_source:
        errors.append("`oncall` names no source: set `alertmanager.url`, a probe, `restarts.enabled` or an extension")

    needs_prometheus = bool(oncall["probes"]) or oncall["restarts"]["enabled"]
    if needs_prometheus and not oncall["prometheus"]["url"]:
        errors.append("`oncall.prometheus.url` is empty, but probes or restarts query it")

    seen = set()
    for n, probe in enumerate(probes(oncall)):
        if not NAME.match(probe["name"]) or probe["name"] in seen:
            errors.append(f"`oncall.probes[{n}].name` must be a unique lowercase name")
        seen.add(probe["name"])
        if not probe["query"].strip():
            errors.append(f"`oncall.probes[{n}].query` is empty")
        if not probe["component"]:
            errors.append(f"`oncall.probes[{n}].component` is empty")

    restarts = oncall["restarts"]
    if not WINDOW.match(restarts["window"]):
        errors.append("`oncall.restarts.window` must be a Prometheus duration such as `30m`")
    if restarts["exclude_namespaces"]:
        try:
            re.compile(restarts["exclude_namespaces"])
        except re.error as e:
            errors.append(f"`oncall.restarts.exclude_namespaces`: {e}")

    for path in oncall["extensions"] + ([oncall["presenter"]] if oncall["presenter"] else []):
        if not str(path).endswith(".py"):
            errors.append(f"`oncall` extension {path!r} must be a .py file, relative to the wiki root")
    return errors


def section_errors(oncall: dict, names: list[str]) -> list[str]:
    errors = []
    if not oncall["sections"]:
        errors.append("`oncall.sections` is empty: the pane would show nothing")

    for n, section in enumerate(sections(oncall)):
        where = f"oncall.sections[{n}]"
        if not section["title"]:
            errors.append(f"`{where}.title` is empty")
        for key, choices in CHOICES.items():
            if section[key] not in choices:
                errors.append(f"`{where}.{key}` must be one of {', '.join(choices)}")
        for key in ("min_severity", "max_severity"):
            if section[key] and section[key] not in names:
                errors.append(f"`{where}.{key}` {section[key]!r} is not one of `oncall.severities`")
        if not isinstance(section["limit"], int) or section["limit"] < 0:
            errors.append(f"`{where}.limit` must be 0 (all) or more")
    return errors

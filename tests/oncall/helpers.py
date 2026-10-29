"""Shared fixtures: an ACME config with the defaults merged, and signals built the way sources build them."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from oncall import defaults  # noqa: E402
from oncall.context import Context  # noqa: E402
from wikiloop.config import merge  # noqa: E402

HOUR = 3600
NOW = 1_800_000_000.0

BASE = {
    "enabled": True,
    "tiers": ["core", "standard"],
    "alertmanager": {"url": "https://alertmanager.acme.example/api/v2/alerts", "link_label": "dashboard"},
    "subject": {
        "labels": ["service"],
        "noun": "services",
        "place_labels": ["namespace", "region", "job"],
        "tier_of": {"core": ["checkout", "payments*"]},
        "env_of": {"staging": ["*-staging"]},
    },
}


def config(**oncall) -> dict:
    return {
        "wiki": {"plugin": "acme-wiki", "owner": "ACME", "domain": "ACME systems"},
        "core": {"path": "core"},
        "oncall": merge(merge(defaults.DEFAULTS, BASE), oncall),
    }


def context(**oncall) -> Context:
    return Context(config(**oncall), ROOT / "example")


def alert(ctx: Context, service: str, name: str = "CheckoutErrors", component: str = "checkout",
          severity: str = "minor", started: str = "", silenced: bool = False, source: str = "alertmanager",
          **labels) -> dict:
    labels = {"service": service, **labels} if service else labels
    return ctx.signal(labels, component, severity, source, name, f"{service or 'x'} {component} failing",
                      started, "", silenced)


def iso(ts: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

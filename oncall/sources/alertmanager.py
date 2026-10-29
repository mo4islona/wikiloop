"""Every active alert, silenced and inhibited ones included, from the Alertmanager API v2.

`[oncall.alertmanager] url` is the alerts endpoint itself: an Alertmanager's own
(`.../api/v2/alerts`) or the same path through a Grafana datasource proxy. A silenced alert stays
in the report, marked, and never raises a problem's severity.
"""
from __future__ import annotations

import re

from oncall.context import Context, Http

URL = re.compile(r"https?://[^\s)\]>\"']+")
ACTIVE = "active=true&silenced=true&inhibited=true"


def collect(ctx: Context) -> list:
    table = ctx.oncall["alertmanager"]
    separator = "&" if "?" in table["url"] else "?"
    alerts = Http(table).get(f"{table['url']}{separator}{ACTIVE}")

    out = []
    for alert in alerts:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})

        raw = labels.get(table["severity_label"], "")
        severity = table["severity_map"].get(raw, raw) or ctx.lowest

        out.append(ctx.signal(
            labels, ctx.component_of(labels), severity, "alertmanager", labels.get("alertname", "?"),
            annotations.get("summary") or labels.get("alertname", ""),
            alert.get("startsAt", ""), link_of(alert, table["link_annotation"]),
            alert.get("status", {}).get("state") == "suppressed"))
    return out


def link_of(alert: dict, annotation: str) -> str:
    """The first web link in the named annotation (bare or markdown), else the rule's generator URL."""
    found = URL.search(alert.get("annotations", {}).get(annotation, "")) if annotation else None
    return found.group(0) if found else alert.get("generatorURL", "")

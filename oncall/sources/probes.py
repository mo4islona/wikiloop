"""Declarative probes: one PromQL query per blind spot, from `[[oncall.probes]]`.

Every series the query returns is one signal. The query carries the threshold (`... > 600`),
so a quiet probe returns nothing. `summary` is a Python format string over the series labels
plus `value`; a label the series lacks prints as `?`.
"""
from __future__ import annotations

from oncall.context import Context


class Labels(dict):
    def __missing__(self, key: str) -> str:
        return "?"


def collect(ctx: Context) -> list:
    out = []
    for probe in ctx.probes:
        for series in ctx.query(probe["query"]):
            labels = dict(series.get("metric", {}))
            value = float(series["value"][1])

            subject = ctx.subject_of(labels)
            tier, _ = ctx.tier_env(subject, labels) if subject else (ctx.default_tier, "")
            severity = ctx.severity_for(probe["severity"], tier)

            out.append(ctx.signal(labels, probe["component"], severity, "probes", probe["name"],
                                  summary_of(probe, labels, value)))
    return out


def summary_of(probe: dict, labels: dict, value: float) -> str:
    if not probe["summary"]:
        return f"{probe['name']}: {value:g}"

    try:
        return probe["summary"].format_map(Labels(labels, value=value))
    except (ValueError, TypeError, IndexError):
        return f"{probe['name']}: {value:g}"

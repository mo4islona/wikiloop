"""How a problem reads on the screen: its label, what is wrong, the error line, where to look.

The engine writes this `view` into every problem in state.json, so the pane and the line under
the prompt only draw it. A wiki whose alert texts need more trimming than `[oncall.present]`
offers supplies a presenter (`[oncall] presenter`), which gets the problem and this view and
returns the view to draw.
"""
from __future__ import annotations

import re

from oncall.context import Context

BRACKET_PREFIX = re.compile(r"^\[[^\]]*\]\s*")
# a restarts summary ends in "(<reason>, exit <code>: <last error line>)": the error gets its own line
RESTART_TAIL = re.compile(r" \((?:[A-Za-z]+|unknown reason), exit .*$")
EXIT_LINE = re.compile(r"exit -?\d+: (.+?)\)?$")


def alert_summary(p: dict) -> str:
    signals = list(p.get("signals", {}).values())
    alert = next((s for s in signals if s["source"] == "alertmanager"), None)
    first = alert or (signals[0] if signals else None)
    return first["summary"] if first else ""


def label_of(p: dict, ctx: Context) -> str:
    # one alert on many subjects: name the alert, not the first subject
    if p["scope"] == "fleet":
        name = (p.get("fleet_group") or ["", p["component"]])[1]
        return f"{name} · {len(p.get('subjects', []))} {ctx.subject['noun']}"

    if p.get("subjects"):
        return f"{p['subjects'][0]} {p['component']}"

    if p["component"] in ("", p["scope"]):
        return p["scope"]
    return f"{p['scope']} {p['component']}"


def what_of(p: dict, ctx: Context) -> str:
    """The alert's sentence without what the label already says."""
    if p["scope"] == "fleet":
        return ", ".join(p.get("subjects", []))

    what = BRACKET_PREFIX.sub("", alert_summary(p).split(" · ")[0])
    for prefix in ctx.oncall["present"]["strip_prefixes"]:
        if what.startswith(prefix):
            what = what[len(prefix):].lstrip()

    for word in [*p.get("subjects", []), p["scope"], p["component"]]:
        if word and what.startswith(f"{word} "):
            what = what[len(word) + 1:]
    return RESTART_TAIL.sub("", what)


def error_of(p: dict) -> str:
    """The last error line the restarts probe read."""
    for s in p.get("signals", {}).values():
        found = EXIT_LINE.search(s["summary"])
        if found:
            return re.sub(r"^Error: ", "", found.group(1))
    return ""


def links_of(p: dict, ctx: Context) -> list:
    """The alert's web view and the channel it reaches; a link a browser cannot open is dropped."""
    signals = list(p.get("signals", {}).values())
    links = []

    # a fleet problem's first subject would stand for all of them
    web = None if p["scope"] == "fleet" else next((s["link"] for s in signals if is_web(s.get("link"))), None)
    if web:
        links.append({"label": ctx.oncall["alertmanager"]["link_label"], "href": web})

    for s in signals:
        is_new_channel = s.get("channel") and is_web(s.get("channel_url")) and all(l["href"] != s["channel_url"] for l in links)
        if is_new_channel:
            links.append({"label": f"#{s['channel']}", "href": s["channel_url"]})
    return links


def is_web(href) -> bool:
    return isinstance(href, str) and href.startswith("https://")


def view_of(p: dict, ctx: Context, presenter=None) -> dict:
    tier = f"{p['tier']}/{p['env']}" if p.get("tier", "-") != "-" else ""
    view = {"label": label_of(p, ctx), "what": what_of(p, ctx), "error": error_of(p),
            "links": links_of(p, ctx), "tier": tier}

    if presenter is not None:
        view = presenter.present(p, dict(view)) or view
    return view

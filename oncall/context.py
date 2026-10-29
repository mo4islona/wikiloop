"""What every part of the watch needs from the config: ranks, thresholds, and how a signal is
named. Sources build their signals through `Context.signal`, so every source files the same
subject under the same problem id."""
from __future__ import annotations

import fnmatch
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from oncall import defaults


class Http:
    """A JSON GET with an optional bearer token from a file or an env var."""

    def __init__(self, table: dict):
        self.token = read_token(table)

    def get(self, url: str):
        headers = {"User-Agent": "wikiloop-oncall"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)


def read_token(table: dict) -> str:
    if table.get("token_env"):
        return os.environ.get(table["token_env"], "").strip()

    if table.get("token_file"):
        return Path(os.path.expanduser(table["token_file"])).read_text().strip()
    return ""


class Prometheus:
    def __init__(self, table: dict):
        self.url = table["url"]
        self.http = Http(table)

    def query(self, expr: str) -> list:
        return self.http.get(self.url + "?" + urllib.parse.urlencode({"query": expr}))["data"]["result"]


class Context:
    def __init__(self, cfg: dict, root: Path):
        self.cfg = cfg
        self.root = root
        self.oncall = cfg["oncall"]
        self.plugin = cfg["wiki"]["plugin"]

        # ranks grow with importance: the first severity and the first tier rank highest
        self.severities = [s["name"] for s in self.oncall["severities"]]
        self.rank = {name: len(self.severities) - i for i, name in enumerate(self.severities)}
        self.lowest = self.severities[-1]
        self.loud = self.rank[self.oncall["loud"]]
        self.floor = self.rank[self.oncall["floor"]]

        self.tiers = list(self.oncall["tiers"])
        self.tier_rank = {tier: len(self.tiers) - i for i, tier in enumerate(self.tiers)}
        self.default_tier = self.tiers[-1] if self.tiers else "-"

        self.t = self.oncall["thresholds"]
        self.subject = self.oncall["subject"]
        self.sections = defaults.sections(self.oncall)
        self.probes = defaults.probes(self.oncall)
        self.prefixes = sorted(self.subject["component_prefixes"].items(), key=lambda kv: -len(kv[0]))
        self._prometheus = None

    @property
    def prometheus(self) -> Prometheus:
        if self._prometheus is None:
            self._prometheus = Prometheus(self.oncall["prometheus"])
        return self._prometheus

    def query(self, expr: str) -> list:
        return self.prometheus.query(expr)

    def severity_for(self, spec, tier: str) -> str:
        """`spec` is a severity name, or tier -> severity with a `default`."""
        if isinstance(spec, str):
            return spec
        return spec.get(tier, spec.get("default", self.oncall["floor"]))

    def subject_of(self, labels: dict) -> str:
        """What a signal is about, '' when it is not subject-scoped."""
        for key in self.subject["labels"]:
            value = labels.get(key, "")
            if value:
                return self.subject["aliases"].get(value, value)
        return ""

    def place_of(self, labels: dict) -> str:
        """Where a signal without a subject belongs: the first place label that says something."""
        for key in self.subject["place_labels"]:
            value = labels.get(key, "")
            if value and value not in self.subject["ignore_places"]:
                return value
        return "global"

    def component_of(self, labels: dict) -> str:
        component = labels.get(self.subject["component_label"], "")
        if not component:
            name = labels.get("alertname", "")
            component = next((c for prefix, c in self.prefixes if name.startswith(prefix)), "")

        # a pod-scoped rule names its container, which is how the restarts probe names the same thing
        component = component or labels.get("container", "")
        return self.subject["component_aliases"].get(component, component) or "other"

    def tier_env(self, subject: str, labels: dict) -> tuple:
        tier = labels.get(self.subject["tier_label"], "")
        if tier not in self.tier_rank:
            tier = matching(self.subject["tier_of"], subject, self.tiers) or self.default_tier

        envs = list(self.subject["env_of"])
        env = labels.get(self.subject["env_label"], "") or matching(self.subject["env_of"], subject, envs)
        return tier, env or self.subject["default_env"]

    def route_of(self, labels: dict, severity: str) -> tuple:
        """The channel where a person sees this alert, and its URL; ('', '') when it reaches none."""
        routes = self.oncall["routes"]
        if not routes["channel"]:
            return "", ""

        value = labels.get(routes["team_label"], "")
        team = routes["teams"].get(value, "") if routes["teams"] else value
        if not team:
            return "", ""

        level = routes["severity_names"].get(severity, severity)
        channel = routes["channel"].format(team=team, severity=level)
        channel_id = routes["channel_ids"].get(channel, "")

        has_url = routes["url"] and ("{id}" not in routes["url"] or channel_id)
        url = routes["url"].format(channel=channel, id=channel_id) if has_url else ""
        return channel, url

    def signal(self, labels: dict, component: str, severity: str, source: str, name: str, summary: str,
               started: str = "", link: str = "", silenced: bool = False) -> dict:
        subject = self.subject_of(labels)
        scope = subject or self.place_of(labels)
        tier, env = self.tier_env(subject, labels) if subject else ("-", "-")

        # every alert name on one subject and component is one problem; a split component keeps
        # one problem per variant (a replica, a provider) so two of them failing stay apart
        variant = labels.get(self.subject["variant_label"], "") if self.subject["variant_label"] else ""
        is_split = component in self.subject["split_components"] and variant
        pid = f"{scope}/{component}/{variant}" if is_split else f"{scope}/{component}"

        channel, channel_url = self.route_of(labels, severity)
        return {
            "id": pid, "scope": scope, "subject": subject, "component": component, "variant": variant,
            "severity": severity if severity in self.rank else self.lowest,
            "source": source, "name": name, "summary": summary, "started": started, "link": link,
            "silenced": silenced, "tier": tier, "env": env, "channel": channel, "channel_url": channel_url,
        }


def matching(patterns: dict, subject: str, order: list) -> str:
    """The first key, in `order`, whose glob patterns match the subject."""
    for key in order:
        if any(fnmatch.fnmatchcase(subject, p) for p in patterns.get(key, [])):
            return key
    return ""

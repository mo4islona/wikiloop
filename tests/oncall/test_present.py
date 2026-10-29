"""The view the screen draws: label, what, error and links, computed by the engine."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import NOW, context  # noqa: E402

from oncall.present import view_of  # noqa: E402


def problem(**over) -> dict:
    p = {
        "id": "search/search", "scope": "search", "component": "search", "severity": "minor",
        "tier": "standard", "env": "prod", "status": "open", "first_seen": NOW, "subjects": ["search"],
        "signals": {"alertmanager:SearchSlow": {"source": "alertmanager", "summary": "search search p99 over 2s"}},
    }
    return {**p, **over}


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.ctx = context(present={"strip_prefixes": ["ACME:"]})

    def test_a_fleet_is_named_by_its_alert_and_lists_its_subjects(self):
        fleet = problem(id="fleet/api/DependencyTimeout", scope="fleet", component="api",
                        subjects=["cart", "search"], fleet_group=["alertmanager", "DependencyTimeout", "api"])

        view = view_of(fleet, self.ctx)

        self.assertEqual(view["label"], "DependencyTimeout · 2 services")
        self.assertEqual(view["what"], "cart, search")

    def test_what_drops_what_the_label_says(self):
        p = problem(signals={"a": {"source": "alertmanager", "summary": "[prod] ACME: search search p99 over 2s · runbook"}})

        self.assertEqual(view_of(p, self.ctx)["what"], "p99 over 2s")

    def test_a_problem_without_subject_is_named_by_its_place(self):
        p = problem(id="monitoring/disk", scope="monitoring", component="disk", subjects=[], tier="-")

        view = view_of(p, self.ctx)

        self.assertEqual((view["label"], view["tier"]), ("monitoring disk", ""))

    def test_the_restart_error_gets_its_own_line(self):
        p = problem(signals={
            "a": {"source": "alertmanager", "summary": "search search reported no data for 30m"},
            "b": {"source": "restarts", "summary": "shop/search-0 restarted 6x in 30m (Error, exit 1: Error: connection refused)"},
        })
        crash = problem(signals={
            "b": {"source": "restarts", "summary": "shop/search-0 restarted 3x in 30m (OOMKilled, exit 137)"},
        })

        self.assertEqual(view_of(p, self.ctx)["what"], "reported no data for 30m")
        self.assertEqual(view_of(p, self.ctx)["error"], "connection refused")
        self.assertEqual(view_of(crash, self.ctx)["what"], "shop/search-0 restarted 3x in 30m")
        self.assertEqual(view_of(crash, self.ctx)["error"], "")

    def test_links_are_the_web_view_and_the_channel_never_a_pod_address(self):
        channel = {"channel": "alerts-search-minor", "channel_url": "https://chat.acme.example/channels/alerts-search-minor"}
        web = problem(signals={"a": {"source": "alertmanager", "summary": "s", "link": "https://grafana.acme.example/d/x", **channel}})
        pod = problem(signals={"a": {"source": "alertmanager", "summary": "s", "link": "http://vmalert-0:8080/alert", **channel}})
        fleet = problem(scope="fleet", fleet_group=["alertmanager", "A", "api"], signals={
            "a": {"source": "alertmanager", "summary": "a", "link": "https://grafana.acme.example/a", **channel},
            "b": {"source": "alertmanager", "summary": "b", "link": "https://grafana.acme.example/b", **channel},
        })

        self.assertEqual([l["label"] for l in view_of(web, self.ctx)["links"]], ["dashboard", "#alerts-search-minor"])
        self.assertEqual([l["label"] for l in view_of(pod, self.ctx)["links"]], ["#alerts-search-minor"])
        self.assertEqual([l["label"] for l in view_of(fleet, self.ctx)["links"]], ["#alerts-search-minor"])

    def test_a_presenter_gets_the_last_word(self):
        presenter = types.SimpleNamespace(present=lambda p, view: {**view, "label": view["label"].upper()})

        self.assertEqual(view_of(problem(), self.ctx, presenter)["label"], "SEARCH SEARCH")


if __name__ == "__main__":
    unittest.main()

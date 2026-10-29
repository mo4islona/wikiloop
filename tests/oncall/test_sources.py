"""Sources turn what they read into signals through the same naming as every other source."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import context  # noqa: E402

from oncall import engine  # noqa: E402
from oncall.sources import alertmanager, probes, restarts  # noqa: E402

PROMETHEUS = {"url": "https://prometheus.acme.example/api/v1/query"}


def series(value: float, **labels) -> dict:
    return {"metric": labels, "value": [0, str(value)]}


class AlertmanagerTests(unittest.TestCase):
    def test_alerts_become_signals_with_severity_link_and_channel(self):
        ctx = context(
            alertmanager={"severity_map": {"warning": "minor"}, "link_annotation": "dashboard"},
            subject={"component_prefixes": {"Checkout": "checkout"}},
            routes={"channel": "alerts-{team}-{severity}", "severity_names": {"info": "minor"},
                    "url": "https://chat.acme.example/channels/{channel}"},
        )
        alerts = [
            {"labels": {"alertname": "CheckoutErrors", "service": "checkout", "severity": "warning", "team": "shop"},
             "annotations": {"summary": "checkout errors over 5%", "dashboard": "[open](https://grafana.acme.example/d/1)"},
             "startsAt": "2027-01-15T08:00:00Z", "status": {"state": "active"}},
            {"labels": {"alertname": "Noise", "service": "search", "severity": "page-me"},
             "annotations": {}, "generatorURL": "http://vmalert-0/x", "status": {"state": "suppressed"}},
        ]

        with mock.patch("oncall.sources.alertmanager.Http.get", return_value=alerts) as get:
            signals = alertmanager.collect(ctx)

        self.assertIn("active=true&silenced=true&inhibited=true", get.call_args[0][0])
        checkout, noise = signals
        self.assertEqual((checkout["id"], checkout["severity"], checkout["tier"]), ("checkout/checkout", "minor", "core"))
        self.assertEqual(checkout["link"], "https://grafana.acme.example/d/1")
        self.assertEqual(checkout["channel_url"], "https://chat.acme.example/channels/alerts-shop-minor")
        self.assertEqual((noise["severity"], noise["silenced"], noise["channel"]), ("info", True, ""))


class ProbeTests(unittest.TestCase):
    def test_each_series_is_a_signal_with_its_tier_severity_and_summary(self):
        probe = {"name": "queue-stalled", "query": "q", "component": "queue",
                 "severity": {"default": "minor", "core": "major"}, "summary": "{queue} holds {value:.0f} ({missing})"}
        ctx = context(probes=[probe], prometheus=PROMETHEUS)
        answer = [series(1500, service="payments-eu", queue="refunds"), series(2000, service="search", queue="index")]

        with mock.patch.object(type(ctx), "query", return_value=answer):
            payments, search = probes.collect(ctx)

        self.assertEqual((payments["severity"], payments["summary"]), ("major", "refunds holds 1500 (?)"))
        self.assertEqual((search["severity"], search["source"], search["name"]), ("minor", "probes", "queue-stalled"))


class RestartTests(unittest.TestCase):
    def answers(self, query: str) -> list:
        if query.startswith("sum by"):
            return [series(4, namespace="shop", pod="cart-0", container="cart"),
                    *[series(1, namespace="shop", pod=f"web-{i}", container="web") for i in range(3)]]
        if "last_terminated_reason" in query:
            return [series(1, namespace="shop", pod="cart-0", container="cart", reason="Error")]
        if "last_terminated_exitcode" in query:
            return [series(1, namespace="shop", pod="cart-0", container="cart")]
        if "kube_pod_info" in query:
            return [series(1, namespace="shop", pod=f"web-{i}", node="node-a") for i in range(3)]
        return []

    def test_a_crash_loop_stays_its_pod_and_one_restart_per_pod_on_a_node_is_one_problem(self):
        ctx = context(restarts={"enabled": True, "exclude_namespaces": "sandbox-.*"}, prometheus=PROMETHEUS)

        with mock.patch.object(type(ctx), "query", side_effect=self.answers) as query:
            signals = restarts.collect(ctx)

        self.assertIn('namespace!~"sandbox-.*"', query.call_args_list[0][0][0])
        crash, node = signals
        self.assertEqual((crash["name"], crash["id"]), ("crash-loop", "shop/cart"))
        self.assertIn("(Error, exit 1)", crash["summary"])
        self.assertEqual((node["id"], node["name"], node["severity"]), ("node/node-a", "node-restarts", "info"))

    def test_redaction_keeps_scheme_and_host_only(self):
        line = restarts.redact('call https://rpc.acme.example/v1/abc?key=1 failed, api_key="s3cret"')

        self.assertNotIn("abc", line)
        self.assertNotIn("s3cret", line)
        self.assertIn("https://rpc.acme.example/<redacted>", line)


class ExtensionTests(unittest.TestCase):
    def test_an_extension_is_a_source_of_its_own(self):
        ctx = context(extensions=["extensions/oncall/regions.py"], prometheus=PROMETHEUS)
        answer = [series(0.92, region="eu-west"), series(0.08, region="us-east")]

        with mock.patch.object(type(ctx), "query", return_value=answer):
            readers = engine.readers(ctx)
            signals = readers["ext:regions"]()

        self.assertEqual(sorted(readers), ["alertmanager", "ext:regions"])
        self.assertEqual(len(signals), 1)
        self.assertEqual((signals[0]["source"], signals[0]["id"]), ("ext:regions", "eu-west/traffic"))

    def test_alerts_only_reads_alertmanager_alone(self):
        ctx = context(extensions=["extensions/oncall/regions.py"], prometheus=PROMETHEUS)

        self.assertEqual(list(engine.readers(ctx, alerts_only=True)), ["alertmanager"])


if __name__ == "__main__":
    unittest.main()

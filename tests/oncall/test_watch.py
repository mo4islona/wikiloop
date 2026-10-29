"""One cycle end to end: the watcher reads a fake Alertmanager and Prometheus, writes state.json
with a ready view per problem, and prints the report."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import ROOT, config  # noqa: E402

ALERTS = [{
    "labels": {"alertname": "CheckoutErrors", "service": "checkout", "severity": "major", "component": "checkout"},
    "annotations": {"summary": "checkout checkout errors over 5%"},
    "startsAt": "2027-01-15T08:00:00Z", "status": {"state": "active"},
}]
QUEUE = {"status": "success", "data": {"resultType": "vector", "result": [
    {"metric": {"service": "search", "queue": "index"}, "value": [0, "4200"]},
]}}


class Fake(BaseHTTPRequestHandler):
    def do_GET(self):
        body = ALERTS if self.path.startswith("/api/v2/alerts") else QUEUE
        payload = json.dumps(body).encode()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class WatchTests(unittest.TestCase):
    def test_one_cycle_writes_state_with_views_and_prints_the_report(self):
        server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"

        probe = {"name": "queue-stalled", "query": "q", "component": "queue", "summary": "{queue} holds {value:.0f}"}
        cfg = config(alertmanager={"url": f"{base}/api/v2/alerts"}, prometheus={"url": f"{base}/api/v1/query"},
                     probes=[probe])

        with tempfile.TemporaryDirectory() as tmp:
            hooks = Path(tmp, "hooks")
            hooks.mkdir()
            (hooks / "wikiloop.json").write_text(json.dumps(cfg))
            state_dir = Path(tmp, "state")

            proc = subprocess.run(
                [sys.executable, str(ROOT / "oncall" / "watch.py"), "--config", str(hooks / "wikiloop.json"),
                 "--state-dir", str(state_dir), "--once"],
                capture_output=True, text=True, timeout=60)
            server.shutdown()
            server.server_close()
            self.assertEqual(proc.returncode, 0, proc.stderr)
            state = json.loads((state_dir / "state.json").read_text())

        self.assertIn("## Major, still open", proc.stdout)
        self.assertIn("first cycle: everything open is listed below", proc.stdout)

        problems = state["problems"]
        self.assertEqual(sorted(problems), ["checkout/checkout", "search/queue"])
        self.assertEqual(problems["checkout/checkout"]["view"]["label"], "checkout checkout")
        self.assertEqual(problems["checkout/checkout"]["view"]["what"], "errors over 5%")
        self.assertEqual(problems["search/queue"]["view"]["what"], "index holds 4200")
        self.assertEqual(state["interval"], 300)
        self.assertEqual(state["health"], {"alertmanager": "ok", "probes": "ok"})


if __name__ == "__main__":
    unittest.main()

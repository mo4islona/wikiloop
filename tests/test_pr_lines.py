"""What `wikiloop pr-lines` hands a reviewer: the whole diff, and hints that point, not judge."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest

from tests.support import CLI, EXAMPLE
from wikiloop.pr_lines import hints


class ReviewContextTests(unittest.TestCase):
    def dump(self, diff: str) -> str:
        diff = textwrap.dedent(diff).lstrip("\n")
        result = subprocess.run([sys.executable, str(CLI), "pr-lines", "-"], input=diff, cwd=EXAMPLE,
                                capture_output=True, text=True, check=True)
        # The reviewer must receive the entire patch, unchanged and in order.
        self.assertIn(diff, result.stdout)
        return result.stdout

    def test_deleted_condition_is_visible(self):
        self.dump("""
            diff --git a/metrics.md b/metrics.md
            --- a/metrics.md
            +++ b/metrics.md
            @@ -1,3 +1,2 @@
             ## Requests
             Requests are rejected when the queue is full.
            -This applies only to streaming requests.
        """)

    def test_hints_point_at_the_added_line(self):
        output = self.dump("""
            diff --git a/metrics.md b/metrics.md
            --- a/metrics.md
            +++ b/metrics.md
            @@ -10,2 +10,2 @@
             ## Requests
            -The limit is fixed.
            +Set `queue.limit` in the values file to change the limit.
        """)
        self.assertIn("metrics.md:11", output)
        self.assertIn("config key: queue.limit", output)


class HintTests(unittest.TestCase):
    def test_timeout_in_hundreds_of_seconds_is_a_value(self):
        self.assertIn("value: 120s", hints("`Checkout_Lag_Critical` (>120s)"))

    def test_status_code_plural_is_not_a_value(self):
        self.assertEqual(hints("the edge 503s, and 429s follow"), [])

    def test_sizes_rates_and_replica_counts_are_flagged(self):
        found = hints("4 replicas, `search-db` ×2 on a 768Gi PV, uplink capped at ~1.16 Gbps")
        for hint in ("replica count: 4 replicas", "replica count: ×2", "value: 768Gi", "value: 1.16 Gbps"):
            self.assertIn(hint, found)

    def test_since_a_date_is_state(self):
        self.assertIn("state wording: since 2026-07-22", hints("toggle OFF since 2026-07-22"))

    def test_date_naming_an_entry_is_a_link(self):
        entries = frozenset({"2026-07-23"})
        self.assertEqual(hints("mechanism: incidents.md 2026-07-23", entries), [])
        self.assertIn("date outside an entry header: 2026-07-24", hints("measured on 2026-07-24", entries))


if __name__ == "__main__":
    unittest.main()

"""The rails: dedup by subject, fleet folding, resolution only after absence with every source
answering, stdout that tells a flap once, and a report that states its freshness."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import HOUR, NOW, alert, context, iso  # noqa: E402

from oncall import engine  # noqa: E402


def run_cycle(ctx, state: dict, signals: list, health: dict | None = None, now: float = NOW) -> list:
    current = engine.fold(signals, state, ctx, now)
    return engine.advance(state, current, health or {"alertmanager": "ok"}, ctx, now)


def kinds(events: list) -> list:
    return [kind for kind, _ in events]


class FoldTests(unittest.TestCase):
    def setUp(self):
        self.ctx = context()

    def test_alert_names_on_one_subject_and_component_are_one_problem(self):
        signals = [alert(self.ctx, "search", "SearchLatency", "search"),
                   alert(self.ctx, "search", "SearchErrors", "search", severity="major")]

        problems = engine.fold(signals, {}, self.ctx, NOW)

        self.assertEqual(list(problems), ["search/search"])
        self.assertEqual(problems["search/search"]["severity"], "major")
        self.assertEqual(len(problems["search/search"]["signals"]), 2)

    def test_a_silenced_alert_describes_but_never_raises_severity(self):
        signals = [alert(self.ctx, "search", "SearchLatency", "search"),
                   alert(self.ctx, "search", "SearchDown", "search", severity="critical", silenced=True)]

        problem = engine.fold(signals, {}, self.ctx, NOW)["search/search"]

        self.assertEqual(problem["severity"], "minor")
        self.assertIn("alertmanager:SearchDown", problem["signals"])

    def test_tier_and_env_come_from_the_subject_patterns(self):
        core = alert(self.ctx, "payments-eu")
        staging = alert(self.ctx, "search-staging", component="search")

        self.assertEqual((core["tier"], core["env"]), ("core", "prod"))
        self.assertEqual((staging["tier"], staging["env"]), ("standard", "staging"))

    def test_a_signal_without_subject_belongs_to_its_place(self):
        s = alert(self.ctx, "", "DiskFull", "disk", namespace="monitoring")

        self.assertEqual((s["id"], s["tier"]), ("monitoring/disk", "-"))

    def test_a_split_component_keeps_one_problem_per_variant(self):
        ctx = context(subject={"split_components": ["replica"], "variant_label": "replica"})
        signals = [alert(ctx, "search", "ReplicaLag", "replica", replica="a"),
                   alert(ctx, "search", "ReplicaLag", "replica", replica="b")]

        self.assertEqual(sorted(engine.fold(signals, {}, ctx, NOW)), ["search/replica/a", "search/replica/b"])


class FleetTests(unittest.TestCase):
    SERVICES = ["cart", "catalog", "checkout", "reviews", "search"]

    def setUp(self):
        self.ctx = context()

    def signals(self, starts: list) -> list:
        return [alert(self.ctx, s, "DependencyTimeout", "api", started=iso(ts)) for s, ts in zip(self.SERVICES, starts)]

    def test_one_alert_name_started_together_on_many_subjects_is_one_fleet_problem(self):
        problems = engine.fold(self.signals([NOW - 600 + i * 60 for i in range(5)]), {}, self.ctx, NOW)

        self.assertEqual(list(problems), ["fleet/api/DependencyTimeout"])
        self.assertEqual(sorted(problems["fleet/api/DependencyTimeout"]["subjects"]), self.SERVICES)

    def test_failures_that_started_far_apart_stay_separate(self):
        problems = engine.fold(self.signals([NOW - i * 2 * HOUR for i in range(5)]), {}, self.ctx, NOW)

        self.assertEqual(len(problems), 5)
        self.assertFalse(any(pid.startswith("fleet/") for pid in problems))

    def test_below_fleet_min_no_fleet(self):
        problems = engine.fold(self.signals([NOW - 60] * 4), {}, self.ctx, NOW)

        self.assertEqual(len(problems), 4)

    def test_an_open_fleet_keeps_its_members_while_two_still_fire(self):
        state = {}
        run_cycle(self.ctx, state, self.signals([NOW - 300] * 5))

        two = self.signals([NOW - 300] * 2)
        problems = engine.fold(two, state, self.ctx, NOW + 300)

        self.assertEqual(list(problems), ["fleet/api/DependencyTimeout"])

    def test_restarts_never_fold(self):
        signals = [alert(self.ctx, s, "crash-loop", "api", source="restarts") for s in self.SERVICES]

        problems = engine.fold(signals, {}, self.ctx, NOW)

        self.assertEqual(len(problems), 5)


class AdvanceTests(unittest.TestCase):
    def setUp(self):
        self.ctx = context(resolve_after=2)
        self.signal = alert(self.ctx, "search", "SearchErrors", "search")

    def test_a_problem_resolves_only_after_resolve_after_absent_cycles(self):
        state = {}
        self.assertEqual(kinds(run_cycle(self.ctx, state, [self.signal])), ["NEW"])

        self.assertEqual(kinds(run_cycle(self.ctx, state, [], now=NOW + 300)), [])
        self.assertEqual(state["problems"]["search/search"]["status"], "open")

        self.assertEqual(kinds(run_cycle(self.ctx, state, [], now=NOW + 600)), ["RESOLVED"])

    def test_a_source_that_is_down_freezes_its_problems(self):
        state = {}
        run_cycle(self.ctx, state, [self.signal])

        down = {"alertmanager": "down: timeout"}
        events = []
        for cycle in range(1, 6):
            events += run_cycle(self.ctx, state, [], down, NOW + cycle * 300)

        self.assertEqual(state["problems"]["search/search"]["status"], "open")
        self.assertEqual(kinds(events), ["SOURCE-DOWN"])
        self.assertEqual(kinds(run_cycle(self.ctx, state, [self.signal], now=NOW + 3600)), ["SOURCE-UP"])

    def test_a_down_source_keeps_its_evidence_after_a_restart(self):
        major = alert(self.ctx, "search", "SearchErrors", "search", severity="major")
        probe = alert(self.ctx, "search", "SearchSlow", "search", source="probes")
        state = {}
        run_cycle(self.ctx, state, [major, probe], {"alertmanager": "ok", "probes": "ok"})

        # a restarted watcher has no last answer to repeat for the source that is down
        down = {"alertmanager": "down: timeout", "probes": "ok"}
        run_cycle(self.ctx, state, [probe], down, NOW + 300)
        problem = state["problems"]["search/search"]
        self.assertEqual(problem["severity"], "major")
        self.assertIn("alertmanager:SearchErrors", problem["signals"])

        for cycle in range(2, 6):
            run_cycle(self.ctx, state, [], down, NOW + cycle * 300)
        self.assertEqual(state["problems"]["search/search"]["status"], "open")

    def test_one_failed_cycle_is_no_source_down(self):
        state = {}
        events = run_cycle(self.ctx, state, [], {"alertmanager": "down: hiccup"})

        self.assertEqual(kinds(events), [])

    def test_a_problem_back_within_the_kept_window_reopens_and_keeps_its_age(self):
        state = {}
        run_cycle(self.ctx, state, [self.signal])
        run_cycle(self.ctx, state, [], now=NOW + 300)
        run_cycle(self.ctx, state, [], now=NOW + 600)

        events = run_cycle(self.ctx, state, [self.signal], now=NOW + 900)
        problem = state["problems"]["search/search"]

        self.assertEqual(kinds(events), ["REOPENED"])
        self.assertEqual((problem["flaps"], problem["first_seen"]), (1, NOW))

    def test_rising_severity_escalates_and_falling_does_not(self):
        state = {}
        run_cycle(self.ctx, state, [self.signal])

        major = alert(self.ctx, "search", "SearchErrors", "search", severity="major")
        self.assertEqual(kinds(run_cycle(self.ctx, state, [major], now=NOW + 300)), ["ESCALATED"])
        self.assertEqual(kinds(run_cycle(self.ctx, state, [self.signal], now=NOW + 600)), [])

    def test_a_fleet_that_gains_subjects_spreads(self):
        services = ["cart", "catalog", "checkout", "reviews", "search", "wishlist"]
        signals = [alert(self.ctx, s, "DependencyTimeout", "api", started=iso(NOW - 60)) for s in services]
        state = {}
        run_cycle(self.ctx, state, signals[:5])

        events = run_cycle(self.ctx, state, signals, now=NOW + 2 * HOUR)

        self.assertEqual(kinds(events), ["SPREAD"])
        self.assertEqual(events[0][1]["spread"], ["wishlist"])


class CollectTests(unittest.TestCase):
    def test_a_failing_source_repeats_its_last_answer(self):
        answers = [["signal"], RuntimeError("timeout")]

        def read():
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        last_good = {}
        engine.collect({"alertmanager": read}, last_good)
        signals, health = engine.collect({"alertmanager": read}, last_good)

        self.assertEqual(signals, ["signal"])
        self.assertTrue(health["alertmanager"].startswith("down: RuntimeError"))


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.ctx = context()
        self.floor = self.ctx.floor

    def problem(self, severity: str = "minor") -> dict:
        return {
            "id": "batch/kubernetes", "scope": "batch", "component": "kubernetes", "severity": severity,
            "tier": "-", "env": "-", "status": "open", "first_seen": 0, "flaps": 0, "subjects": [],
            "signals": {"a": {"source": "alertmanager", "name": "KubePodsPending", "summary": "pods unschedulable"}},
        }

    def shown(self, kind: str, p: dict, now: float) -> list:
        lines = engine.stream([(kind, p)] if kind else [], {p["id"]: p}, self.floor, now, self.ctx)
        return [line for line, is_shown in lines if is_shown]

    def test_a_flap_is_told_once_and_its_end_after_it_stays_away(self):
        quiet = self.ctx.t["flap_quiet"]
        p = self.problem()
        self.assertEqual(len(self.shown("NEW", p, 0)), 1)

        p.update(status="resolved", resolved_at=600)
        self.assertEqual(len(self.shown("RESOLVED", p, 600)), 1)

        p.update(status="open", flaps=1, reopened_at=900)
        self.assertEqual(len(self.shown("REOPENED", p, 900)), 1)

        # the same pair again: stdout already says open, and this resolve may not hold
        p.update(status="resolved", resolved_at=1200)
        self.assertEqual(self.shown("RESOLVED", p, 1200), [])
        p.update(status="open", flaps=2, reopened_at=1500)
        self.assertEqual(self.shown("REOPENED", p, 1500), [])

        p.update(status="resolved", resolved_at=1800)
        self.assertEqual(self.shown("RESOLVED", p, 1800), [])
        self.assertEqual(self.shown("", p, 1800 + quiet - 1), [])

        settled = self.shown("", p, 1800 + quiet)
        self.assertEqual(len(settled), 1)
        self.assertIn("RESOLVED (away for", settled[0])
        self.assertEqual(self.shown("", p, 1800 + 2 * quiet), [])

    def test_an_escalation_back_to_a_told_severity_is_quiet(self):
        p = self.problem("minor")
        self.assertEqual(len(self.shown("ESCALATED", p, 0)), 1)

        # down to info is no event; back to minor tells nothing new
        p["severity"] = "minor"
        self.assertEqual(self.shown("ESCALATED", p, HOUR), [])

        p["severity"] = "major"
        self.assertEqual(len(self.shown("ESCALATED", p, 2 * HOUR)), 1)

    def test_a_resolve_long_after_a_reopen_is_told_at_once(self):
        quiet = self.ctx.t["flap_quiet"]
        p = self.problem()
        p.update(status="resolved", resolved_at=quiet + 1, flaps=1, reopened_at=0, shown="open:minor")

        self.assertEqual(len(self.shown("RESOLVED", p, quiet + 1)), 1)

    def test_below_the_floor_stays_off_stdout(self):
        p = self.problem("info")

        self.assertEqual(self.shown("NEW", p, 0), [])
        self.assertEqual(self.shown("ESCALATED", p, 0), [])


class RenderTests(unittest.TestCase):
    def test_the_report_states_its_freshness_and_follows_the_sections(self):
        ctx = context()
        state = {}
        signals = [alert(ctx, "checkout", severity="major"), alert(ctx, "search", "SearchSlow", "search"),
                   alert(ctx, "reviews", "ReviewsLag", "reviews", severity="info"),
                   alert(ctx, "cart", "CartErrors", "cart", severity="info")]
        run_cycle(ctx, state, signals)
        run_cycle(ctx, state, signals[:3], now=NOW + 300)
        run_cycle(ctx, state, signals[:3], now=NOW + 600)

        report = engine.render(state, [], 300, False, ctx, NOW + 600)

        self.assertIn("a report older than two cycles is no evidence of health", report)
        self.assertLess(report.index("## Major, still open"), report.index("## Minor, still open"))
        self.assertIn("## Resolved, last 6h", report)
        self.assertIn("- and 1 more below minor", report)
        self.assertIn("**reviews/reviews**", report.split("## Other open problems")[1])


if __name__ == "__main__":
    unittest.main()

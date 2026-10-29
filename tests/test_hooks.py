"""The Stop, SessionStart and candidate-gate hooks against synthetic transcripts and tool calls."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import HOOKS, resolved_config

PLUGIN = "acme-wiki"
GOOD = "Symptom: s\nRoot cause: r\nLesson: l\nWhy the wiki: w\nNot repo or vendor: n"
NO_SECOND = "Symptom: s\nRoot cause: r\nLesson: l\nWhy the wiki: w"
WHERE_ONLY = "Symptom: s\nRoot cause: r\nLesson: l\nWhere: debug-checkout/incidents.md"


def tool(name: str, inp: dict) -> dict:
    return {"hook_event_name": "PostToolUse", "tool_name": name, "tool_input": inp}


def skill(name: str) -> dict:
    return tool("Skill", {"skill": name})


def bash(cmd: str) -> dict:
    return tool("Bash", {"command": cmd})


def prompt(text: str = "ok, makes sense") -> dict:
    return {"hook_event_name": "UserPromptSubmit", "prompt": text}


KUBE = [bash(f"kubectl -n checkout get pods -l app={i}") for i in range(4)] + [bash("psql -c 'select 1'")]
REPLY = [prompt()]
CODEX = {"turn_id": "turn-1"}


class HookCase(unittest.TestCase):
    config: Path

    @classmethod
    def setUpClass(cls):
        cls.config = resolved_config()
        cls.cache = tempfile.mkdtemp()

    def hook(self, script: str, payload: dict, entrypoint: str | None = "cli") -> dict | None:
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_ENTRYPOINT", "PLUGIN_ROOT")}
        env.update({"XDG_CACHE_HOME": self.cache, "CLAUDE_PLUGIN_ROOT": "/plugin"})
        if entrypoint:
            env["CLAUDE_CODE_ENTRYPOINT"] = entrypoint

        proc = subprocess.run([sys.executable, str(HOOKS / script), str(self.config)], input=json.dumps(payload),
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else None


class StopTests(HookCase):
    def run_session(self, events: list[dict], session: str, active: bool = False, entrypoint: str | None = "cli",
                    extra: dict | None = None) -> dict | None:
        """Feed the events through track.py, then stop."""
        base = {"session_id": session, "transcript_path": None, **(extra or {})}
        for event in events:
            self.assertIsNone(self.hook("track.py", {**base, **event}, entrypoint), "track.py prints nothing")
        return self.hook("stop.py", {**base, "hook_event_name": "Stop", "stop_hook_active": active}, entrypoint)

    def start(self, session: str) -> dict:
        return self.hook("session_start.py", {"session_id": session, "transcript_path": "/t.jsonl", "source": "resume"})

    def asks(self, out: dict | None) -> bool:
        return bool(out and out.get("decision") == "block" and out.get("reason"))

    def test_signals(self):
        self.assertFalse(self.asks(self.run_session(REPLY, "s1")), "no signals")
        self.assertTrue(self.asks(self.run_session([skill(f"{PLUGIN}:debug-checkout")] + REPLY, "s2")), "debug skill")
        self.assertFalse(self.asks(self.run_session(REPLY, "s2")), "asked once")
        self.assertTrue(self.asks(self.run_session([prompt(f"/{PLUGIN}:debug-checkout")] + REPLY, "s3")), "typed command")
        self.assertFalse(self.asks(self.run_session([skill(f"{PLUGIN}:map-infra")] + REPLY, "s4")), "map skill alone")
        self.assertFalse(self.asks(self.run_session([skill("other-wiki:debug-checkout")] + REPLY, "s5")), "another plugin")
        self.assertFalse(self.asks(self.run_session(KUBE[:4] + REPLY, "s6")), "below threshold")
        self.assertTrue(self.asks(self.run_session(KUBE + REPLY, "s7")), "five shell steps")
        self.assertFalse(self.asks(self.run_session([bash("ls"), bash("git status"), prompt()], "s8")), "plain bash")

        mcp = [tool("mcp__grafana__query_prometheus", {}), tool("mcp__grafana__query_loki_logs", {})]
        self.assertTrue(self.asks(self.run_session(mcp + KUBE[:3] + REPLY, "s9")), "configured mcp tools count")
        pattern = [bash("curl https://grafana.acme.example/api/ds/query")] * 5
        self.assertTrue(self.asks(self.run_session(pattern + REPLY, "s10")), "configured pattern counts")

        read = bash("sed -n 1,80p /plugin/skills/debug-checkout/SKILL.md")
        self.assertTrue(self.asks(self.run_session([read] + REPLY, "s11")), "a skill read as a file counts as a load")

    def test_outside_the_interactive_cli(self):
        self.assertFalse(self.asks(self.run_session(KUBE + REPLY, "s20", active=True)), "stop_hook_active")
        self.assertFalse(self.asks(self.run_session(KUBE + REPLY, "s21", entrypoint="sdk-cli")), "claude -p")
        self.assertFalse(self.asks(self.run_session(KUBE + REPLY, "s22", entrypoint=None)), "no entrypoint")

    def test_codex(self):
        self.assertTrue(self.asks(self.run_session(KUBE + REPLY, "c1", entrypoint=None, extra=CODEX)), "interactive Codex")
        self.assertFalse(self.asks(self.run_session(REPLY, "c1", entrypoint=None, extra=CODEX)), "asked once")
        self.assertFalse(self.asks(self.run_session(REPLY + KUBE, "c2", entrypoint=None, extra=CODEX)),
                         "codex exec: the one prompt comes before the steps")
        argv = tool("Bash", {"command": ["bash", "-lc", "kubectl get pods"]})
        self.assertTrue(self.asks(self.run_session([argv] * 5 + REPLY, "c3", entrypoint=None, extra=CODEX)),
                        "a command passed as argv")

    def test_reason(self):
        reason = self.run_session(KUBE + REPLY, "s30")["reason"]
        self.assertIn("/plugin/skills", reason)
        self.assertIn("python3 /plugin/../bin/wikiloop candidate file", reason)
        self.assertIn("Why the wiki", reason)
        self.assertIn("Not repo or vendor", reason)
        self.assertIn("swap ACME for any other company", reason)
        self.assertLess(reason.index("candidate search"), reason.index("candidate file"))
        self.assertLess(reason.index("wiki: nothing new"), reason.index("candidate search"))
        self.assertNotIn("{{", reason)

    def test_handled_findings(self):
        contribute = skill(f"{PLUGIN}:wiki-contribute")
        filed_cli = bash("python3 /plugin/core/bin/wikiloop candidate file -t t <<'EOF'\nx\nEOF")
        filed_gh = bash("gh issue create -R acme/ai-wiki -l candidate -t t -b b")
        commented = bash("python3 /plugin/core/bin/wikiloop candidate comment 12 < note.md")

        self.assertFalse(self.asks(self.run_session(KUBE + [contribute] + REPLY, "s40")), "contribute after")
        self.assertFalse(self.asks(self.run_session(KUBE + [filed_cli] + REPLY, "s41")), "filed through the CLI")
        self.assertFalse(self.asks(self.run_session(KUBE + [filed_gh] + REPLY, "s42")), "filed through gh")
        self.assertFalse(self.asks(self.run_session(KUBE + [commented] + REPLY, "s43")), "commented")
        self.assertTrue(self.asks(self.run_session(KUBE + REPLY, "s40")), "a new burst asks again")

    def test_reask_interval(self):
        self.assertTrue(self.asks(self.run_session(KUBE + REPLY, "s50")))
        self.assertFalse(self.asks(self.run_session(KUBE * 3 + REPLY, "s50")), "15 more steps in all")
        self.assertTrue(self.asks(self.run_session(KUBE + REPLY, "s50")), "20 more steps in all")

    def test_the_finding_must_be_read_first(self):
        self.assertFalse(self.asks(self.run_session(KUBE, "s60")), "no reply yet")
        self.assertFalse(self.asks(self.run_session(REPLY + KUBE, "s61")), "steps after the reply")
        self.assertTrue(self.asks(self.run_session(REPLY, "s61")), "a reply after the last step")

        injected = ["Stop hook feedback:\nacme-wiki: 5 steps", "<task-notification>x</task-notification>", "/compact",
                    "This session is being continued from a previous conversation", "[Request interrupted by user]"]
        for n, text in enumerate(injected):
            self.assertFalse(self.asks(self.run_session(KUBE + [prompt(text)], f"s62-{n}")), text)

    def test_baseline_after_resume(self):
        self.run_session(KUBE * 30 + REPLY, "s70", active=True)
        started = self.start("s70")
        context = started["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"{PLUGIN}:wiki-contribute", context)
        self.assertIn("this session's transcript is /t.jsonl", context, "report line: the example has a bucket")

        self.assertFalse(self.asks(self.run_session(REPLY, "s70")), "backlog at resume")
        self.assertFalse(self.asks(self.run_session(KUBE[:4] + REPLY, "s70")), "four new steps")
        self.assertTrue(self.asks(self.run_session(KUBE[4:] + REPLY, "s70")), "five new steps")


class NoReportTests(HookCase):
    @classmethod
    def setUpClass(cls):
        cls.config = resolved_config({"report_session": {"kind": "none"}})
        cls.cache = tempfile.mkdtemp()

    def test_no_bucket_no_report_line(self):
        out = self.hook("session_start.py", {"session_id": "n1", "transcript_path": "/t.jsonl"})
        self.assertNotIn("transcript is", out["hookSpecificOutput"]["additionalContext"])


class GateTests(HookCase):
    def gate(self, command: str, cwd: str = "/work/other-repo", tool_name: str = "Bash") -> dict | None:
        payload = {"tool_name": tool_name, "tool_input": {"command": command}, "cwd": cwd}
        return self.hook("candidate_gate.py", payload)

    def denied(self, out: dict | None) -> bool:
        return bool(out and out["hookSpecificOutput"]["permissionDecision"] == "deny")

    def file(self, body: str, cmd: str = "gh issue create -R acme/ai-wiki -l candidate -t t") -> str:
        return f"{cmd} -b '{body}'"

    def test_scope(self):
        self.assertFalse(self.denied(self.gate("", tool_name="Read")))
        self.assertFalse(self.denied(self.gate("kubectl get pods")))
        self.assertFalse(self.denied(self.gate(self.file(WHERE_ONLY, "gh issue create -R acme/infra -l candidate -t t"))))
        self.assertFalse(self.denied(self.gate(self.file(WHERE_ONLY, "gh issue create -R acme/ai-wiki -l bug -t t"))))
        self.assertTrue(self.denied(self.gate(self.file(WHERE_ONLY, "gh issue create -l candidate -t t"), cwd="/w/ai-wiki")))
        self.assertFalse(self.denied(self.gate(self.file(WHERE_ONLY, "gh issue create -l candidate -t t"))))

    def test_lines(self):
        self.assertFalse(self.denied(self.gate(self.file(GOOD))))
        self.assertFalse(self.denied(self.gate(self.file("**Why the wiki:** w\n**Not repo or vendor:** n"))))

        out = self.gate(self.file(WHERE_ONLY))
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertTrue(self.denied(out))
        self.assertIn("`Why the wiki:`", reason)
        self.assertIn("`Not repo or vendor:`", reason)
        self.assertIn("wiki: nothing new", reason)

        reason = self.gate(self.file(NO_SECOND))["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertNotIn("`Why the wiki:`", reason)

    def test_body_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "good.md").write_text(GOOD)
            (Path(tmp) / "bad.md").write_text(WHERE_ONLY)
            base = "gh issue create -R acme/ai-wiki -l candidate -t t"
            self.assertFalse(self.denied(self.gate(f"{base} --body-file {tmp}/good.md")))
            self.assertTrue(self.denied(self.gate(f"{base} --body-file {tmp}/bad.md")))
            self.assertFalse(self.denied(self.gate(f"{base} -F good.md", cwd=tmp)))


if __name__ == "__main__":
    unittest.main()

"""The secret scan: the lint's bar, the redaction, and what `report-session` uploads.

Every synthetic secret is assembled at runtime, so this file never matches the scan itself.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests.support import resolved_config
from tests.test_core import MINIMAL, wiki
from wikiloop import report_session
from wikiloop.config import load
from wikiloop.lint import lint
from wikiloop.secret_scan import find, redact_text, wiki_tokens


def rnd(n: int) -> str:
    return ("aB3dE5gH7jK9mN2pQ4rS6tU8vW0xY1z" * 8)[:n]


KEY_HEAD = "-----BEGIN " + "PRIVATE KEY-----"
KEY_TAIL = "-----END " + "PRIVATE KEY-----"
KEY_BODY = ["MIIEvQIBADAN" + rnd(52), rnd(64), rnd(40) + "=="]

SECRETS = {
    "GitHub classic token": "gh" + "p_" + rnd(36),
    "GitHub fine-grained token": "github" + "_pat_" + rnd(22) + "_" + rnd(59),
    "Slack token": "xo" + "xb-" + "1234567890-" + rnd(24),
    "AWS access key": "AK" + "IA" + "Q3EGRZ7XN2MPLW4K",
    "Google API key": "AI" + "za" + rnd(35),
    "Google OAuth token": "ya" + "29." + rnd(40),
    "Grafana token": "gl" + "sa_" + rnd(32) + "_1a2b3c4d",
    "GitLab token": "gl" + "pat-" + rnd(20),
    "JWT": "ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "J" + rnd(30) + "." + rnd(43),
}
# Values only: the key around them is what the scan reads.
FIELDS = {
    "JSON password": ('{"password": "%s"}', "Pa55" + rnd(14) + "!"),
    "compact JSON secret": ('{"secret":"%s"}', rnd(24)),
    "JSON token, escaped in a transcript": ('{\\"api_token\\": \\"%s\\"}', rnd(28)),
    "YAML secret": ("  client_secret: %s", rnd(30)),
    "env var": ("DB_PASSWORD=%s", rnd(20)),
    "URL credentials": ("postgres://app:%s@db.internal:5432/app", rnd(18)),
    "bearer header": ("Authorization: Bearer %s", rnd(40)),
    "CLI flag": ("tool login --token %s", rnd(32)),
}


def record(content: str) -> str:
    """One transcript line, compact like the ones Claude Code writes."""
    rec = {"type": "user", "message": {"content": [{"type": "tool_result", "content": content}]}}
    return json.dumps(rec, separators=(",", ":")) + "\n"


class LintBar(unittest.TestCase):
    def test_token_shapes(self):
        for kind, secret in SECRETS.items():
            with self.subTest(kind):
                self.assertTrue(find(f"use {secret} here"))

    def test_secret_fields(self):
        for kind, (template, value) in FIELDS.items():
            with self.subTest(kind):
                self.assertTrue(find(template % value))

    def test_private_keys(self):
        self.assertEqual(find(KEY_HEAD), ["private key"])
        self.assertTrue(find("-----BEGIN " + "ENCRYPTED PRIVATE KEY-----"))
        self.assertTrue(find("-----BEGIN " + "OPENSSH PRIVATE KEY-----"))

    def test_prose_passes(self):
        prose = [
            "acme_checkout_latency_ms is the lag in milliseconds",
            "curl -H 'Authorization: Bearer $TOKEN' https://example.com",
            "token: <your token>",
            "password: $(kubectl get secret db -o jsonpath='{.data.admin-password}')",
            "max_tokens: 64000",
            "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
            "(`secret db, key admin-password`)",
            "token = os.environ['GITHUB_TOKEN']",
            "the bearer token expires after an hour",
        ]
        for line in prose:
            with self.subTest(line):
                self.assertEqual(find(line), [])

    def test_wiki_token_shapes(self):
        key = "acme" + "_" + rnd(32)
        cfg = load(wiki(MINIMAL + '[lint]\nsecret_patterns = ["\\\\bacme_[A-Za-z0-9]{32}"]\n'))

        self.assertEqual(find(key), [])
        self.assertEqual(find(key, wiki_tokens(cfg)), ["wiki token"])
        self.assertNotIn(key, redact_text(record(key), wiki_tokens(cfg))[0])


class LintScansEveryFile(unittest.TestCase):
    def test_secret_outside_skills_fails(self):
        root = wiki(MINIMAL)
        try:
            (root / "extensions" / "lint").mkdir(parents=True)
            (root / "extensions" / "lint" / "check.py").write_text(
                f'TOKEN = "{SECRETS["GitHub classic token"]}"\ndef check(ctx):\n    pass\n')
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)

            errors = lint(root, load(root)).errors
        finally:
            shutil.rmtree(root, ignore_errors=True)

        secret_errors = [e for e in errors if "looks like a secret" in e]
        self.assertEqual(len(secret_errors), 1, errors)
        self.assertIn("extensions/lint/check.py: line 1", secret_errors[0])


class Redaction(unittest.TestCase):
    def assert_gone(self, out: str, *secrets: str):
        for s in secrets:
            self.assertNotIn(s, out)

    def test_every_shape_in_a_transcript(self):
        lines = [record(f"found {s} in the env") for s in SECRETS.values()]
        lines += [record(t % v) for t, v in FIELDS.values()]
        out, _ = redact_text("".join(lines))

        self.assert_gone(out, *SECRETS.values(), *(v for _, v in FIELDS.values()))
        for line in out.splitlines():
            json.loads(line)

    def test_raw_private_key_goes_whole(self):
        note = "\n".join(["The session printed this:", KEY_HEAD, *KEY_BODY, KEY_TAIL, "and then hung."]) + "\n"
        out, _ = redact_text(note)

        self.assert_gone(out, KEY_HEAD, KEY_TAIL, *KEY_BODY)
        self.assertIn("The session printed this:", out)
        self.assertIn("and then hung.", out)

    def test_escaped_private_key_goes_whole(self):
        pem = "\n".join([KEY_HEAD, *KEY_BODY, KEY_TAIL]) + "\n"
        service_account = json.dumps({"type": "service_account", "private_key": pem})
        out, _ = redact_text(record(pem) + record(service_account))

        self.assert_gone(out, *KEY_BODY, "PRIVATE KEY")
        for line in out.splitlines():
            json.loads(line)

    def test_truncated_private_key(self):
        cut = "\n".join([KEY_HEAD, *KEY_BODY[:2]])
        out, _ = redact_text(record(cut + "\n[output truncated]"))

        self.assert_gone(out, *KEY_BODY[:2])
        self.assertIn("[output truncated]", out)
        json.loads(out)

    def test_usage_numbers_survive(self):
        line = json.dumps({"usage": {"input_tokens": 12345678, "cache_read_input_tokens": 98765432}}) + "\n"
        self.assertEqual(redact_text(line), (line, 0))


FAKE_GCLOUD = """#!/bin/sh
[ "$1 $2" = "storage cp" ] && cp "$4" "$UPLOADS/"
"""


class ReportSession(unittest.TestCase):
    def test_upload_carries_no_secret(self):
        token = SECRETS["GitHub classic token"]
        password = FIELDS["JSON password"][1]
        config = resolved_config({"report_session": {"kind": "gcs", "bucket": "gs://acme-sessions"}})
        tmp = Path(tempfile.mkdtemp(prefix="wikiloop-report-"))

        try:
            bin_dir, uploads = tmp / "bin", tmp / "uploads"
            bin_dir.mkdir()
            uploads.mkdir()
            (bin_dir / "gcloud").write_text(FAKE_GCLOUD)
            (bin_dir / "gcloud").chmod(0o755)

            transcript = tmp / "session.jsonl"
            transcript.write_text(
                '{"timestamp":"2026-10-29T10:00:00Z","type":"user"}\n'
                + record(f'export GH_TOKEN={token}\n{{"password": "{password}"}}')
                + record("\n".join([KEY_HEAD, *KEY_BODY, KEY_TAIL]))
            )

            env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "UPLOADS": str(uploads),
                   "CLAUDE_PLUGIN_ROOT": str(config.parent.parent)}
            out = io.StringIO()
            with mock.patch.dict(os.environ, env), redirect_stdout(out):
                code = report_session.main([str(transcript), f"it pasted my token {token} back to me"])

            self.assertEqual(code, 0, out.getvalue())
            sent = {p.name: p.read_text() for p in uploads.iterdir()}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(config.parent.parent, ignore_errors=True)

        self.assertEqual(sorted(sent), ["note.md", "transcript.jsonl"])
        for name, text in sent.items():
            with self.subTest(name):
                self.assertNotIn(token, text)
                self.assertNotIn(password, text)
                for line in KEY_BODY:
                    self.assertNotIn(line, text)
        self.assertIn("it pasted my token <redacted> back to me", sent["note.md"])
        self.assertIn("4 strings redacted", out.getvalue())  # token, password, key; token in the note


if __name__ == "__main__":
    unittest.main()

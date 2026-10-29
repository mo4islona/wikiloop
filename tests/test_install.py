"""The generated installer, run against the example: isolated homes, fake CLIs, no network."""
import errno
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from tests.support import EXAMPLE

INSTALL = EXAMPLE / "install.sh"
BOOTSTRAP = EXAMPLE / "bootstrap.sh"
MARKET = "acme-wiki"
PLUGIN = "acme-wiki@acme-wiki"
REPO = "acme/ai-wiki"

# Only the CLI boundary is mocked. The real shell, JSON handling, settings writes,
# argument parsing, and terminal selection run in every scenario.
FAKE_CLI = r'''
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ["TEST_STATE"])
with (root / "calls").open("a") as f:
    f.write(json.dumps([name, *args]) + "\n")
call = " ".join([name, *args])
if os.environ.get("TEST_FAIL") == call:
    sys.exit(1)
market_name = os.environ["TEST_MARKET"]
if name == "gh":
    if args[:1] == ["api"] and "contents/install.sh" in args[1]:
        print(pathlib.Path(os.environ["TEST_INSTALL"]).read_text())
    sys.exit(0)
if os.environ.get("TEST_BAD_JSON") and name == "codex" and args[:3] == ["plugin", "marketplace", "list"]:
    print("invalid json")
    sys.exit(0)
if name == "git" or "--help" in args:
    sys.exit(0)
market = root / (name + "-market")
plugin = root / (name + "-plugin")
if args[:3] == ["plugin", "marketplace", "list"]:
    if name == "codex":
        print(json.dumps({"marketplaces": [{"name": market_name}] if market.exists() else []}))
    elif market.exists():
        print("  " + market_name)
elif args[:3] == ["plugin", "marketplace", "add"]:
    market.touch()
    if name == "claude":
        path = pathlib.Path.home() / ".claude/plugins/known_marketplaces.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({market_name: {}, "other": {"autoUpdate": False}}))
elif args[:2] in (["plugin", "install"], ["plugin", "add"]):
    plugin.write_text("enabled" if not os.environ.get("TEST_DISABLED") else "disabled")
elif args[:2] == ["plugin", "list"]:
    if name == "codex":
        print(json.dumps({"installed": [{"pluginId": market_name + "@" + market_name, "installed": True,
              "enabled": plugin.read_text() == "enabled"}] if plugin.exists() else [], "available": []}))
    elif plugin.exists():
        print(market_name + "@" + market_name)
elif args[:3] not in (["plugin", "marketplace", "update"], ["plugin", "marketplace", "upgrade"]):
    sys.exit("Unexpected CLI call: " + call)
'''


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wiki-installer-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        self.env = {
            "PATH": str(self.bin), "HOME": str(self.home),
            "CODEX_HOME": str(self.home / ".codex"),
            "TEST_STATE": str(self.root), "TEST_INSTALL": str(INSTALL), "TEST_MARKET": MARKET,
        }
        for name in ("bash", "python3", "uname", "grep", "cat", "dirname", "mkdir", "mktemp", "rm"):
            (self.bin / name).symlink_to(shutil.which(name))
        for name in ("claude", "codex", "git", "gh"):
            path = self.bin / name
            path.write_text(f"#!{sys.executable}\n" + FAKE_CLI)
            path.chmod(0o755)

    def run_install(self, *args, script=INSTALL):
        return subprocess.run(
            ["/bin/bash", str(script), *args], env=self.env,
            stdin=subprocess.DEVNULL, text=True, capture_output=True,
            start_new_session=True, timeout=20,
        )

    def calls(self):
        path = self.root / "calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def mutations(self):
        return [c for c in self.calls() if "--help" not in c and any(
            op in c for op in ("add", "install", "update", "upgrade"))]

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_codex_only_without_claude(self):
        (self.bin / "claude").unlink()
        self.assert_ok(self.run_install("--agents", "codex"))
        self.assertEqual(self.mutations(), [
            ["codex", "plugin", "marketplace", "add", REPO, "--ref", "main"],
            ["codex", "plugin", "add", PLUGIN],
        ])
        self.assertFalse((self.home / ".claude").exists())
        self.assertFalse(any(c[0] == "claude" for c in self.calls()))

    def test_claude_only_without_codex_and_preserves_settings(self):
        (self.bin / "codex").unlink()
        self.assert_ok(self.run_install("--agents", "claude"))
        known = json.loads((self.home / ".claude/plugins/known_marketplaces.json").read_text())
        self.assertTrue(known[MARKET]["autoUpdate"])
        self.assertEqual(known["other"], {"autoUpdate": False})
        self.assertFalse(any(c[0] == "codex" for c in self.calls()))

    def test_both_and_repeat_install(self):
        self.assert_ok(self.run_install("--agents", "all"))
        mutations = self.mutations()
        self.assertEqual(len(mutations), 4)
        self.assert_ok(self.run_install("--agents", "claude,codex"))
        self.assertEqual(self.mutations(), mutations)

    def test_check_is_read_only(self):
        self.assert_ok(self.run_install("--agents", "all", "--check"))
        self.assertEqual(self.mutations(), [])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_headless_check_detects_agents(self):
        (self.bin / "claude").unlink()
        self.assert_ok(self.run_install("--check"))
        self.assertEqual(self.mutations(), [])
        self.assertTrue(any(c[0] == "codex" for c in self.calls()))

    def test_headless_install_requires_selection(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 2)
        self.assertIn("No terminal", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_invalid_arguments_do_not_mutate(self):
        for args in (("--agents",), ("--project",), ("--agents", "cursor"),
                     ("--agents", "codex,"), ("--check", "--update"),
                     ("--project", "x", "--agents", "codex"),
                     ("--project", "x", "--update")):
            with self.subTest(args=args):
                self.assertEqual(self.run_install(*args).returncode, 2)
                self.assertEqual(self.calls(), [])

    def test_missing_selected_cli_blocks_all_installs(self):
        (self.bin / "codex").unlink()
        self.assertNotEqual(self.run_install("--agents", "all").returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_older_codex_is_reported(self):
        self.env["TEST_FAIL"] = "codex plugin --help"
        result = self.run_install("--agents", "codex")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Codex plugin CLI", result.stdout)
        self.assertEqual(self.mutations(), [])

    def test_update_both_refreshes_codex_installed_copy(self):
        self.assert_ok(self.run_install("--agents", "all", "--update"))
        self.assertEqual(self.mutations(), [
            ["claude", "plugin", "marketplace", "update", MARKET],
            ["codex", "plugin", "marketplace", "upgrade", MARKET],
            ["codex", "plugin", "add", PLUGIN],
        ])

    def test_update_errors_do_not_report_success(self):
        for agent, command in (("claude", "claude plugin marketplace update " + MARKET),
                               ("codex", "codex plugin marketplace upgrade " + MARKET),
                               ("codex", "codex plugin add " + PLUGIN)):
            with self.subTest(command=command):
                self.env["TEST_FAIL"] = command
                result = self.run_install("--agents", agent, "--update")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("updated;", result.stdout)

    def test_install_errors_do_not_report_success(self):
        for command in ("codex plugin marketplace list --json",
                        "codex plugin marketplace add " + REPO + " --ref main",
                        "codex plugin add " + PLUGIN):
            with self.subTest(command=command):
                self.env["TEST_FAIL"] = command
                result = self.run_install("--agents", "codex")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("done.", result.stdout)

    def test_invalid_marketplace_json_does_not_mutate(self):
        self.env["TEST_BAD_JSON"] = "1"
        result = self.run_install("--agents", "codex")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_repository_access_failure_blocks_install(self):
        self.env["TEST_FAIL"] = f"git ls-remote -q https://github.com/{REPO}.git HEAD"
        self.assertNotEqual(self.run_install("--agents", "all").returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_missing_upgrade_support_blocks_update(self):
        self.env["TEST_FAIL"] = "codex plugin marketplace upgrade --help"
        self.assertNotEqual(self.run_install("--agents", "all", "--update").returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_auto_update_write_error_is_reported(self):
        self.assert_ok(self.run_install("--agents", "claude"))
        known = self.home / ".claude/plugins/known_marketplaces.json"
        known.write_text("invalid json")
        result = self.run_install("--agents", "claude")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("done.", result.stdout)
        self.assertEqual(known.read_text(), "invalid json")

    def test_disabled_codex_plugin_is_reenabled(self):
        (self.root / "codex-market").touch()
        (self.root / "codex-plugin").write_text("disabled")
        self.assert_ok(self.run_install("--agents", "codex"))
        self.assertEqual(self.mutations(), [["codex", "plugin", "add", PLUGIN]])

    def test_failed_enable_is_not_reported_as_success(self):
        self.env["TEST_DISABLED"] = "1"
        result = self.run_install("--agents", "codex")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("done.", result.stdout)

    def test_project_implies_claude_and_preserves_existing_settings(self):
        project = self.root / "project with spaces"
        settings = project / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"enabledPlugins": ["other@other"], "otherSetting": 42}')
        self.assert_ok(self.run_install("--project", str(project)))
        data = json.loads(settings.read_text())
        self.assertEqual(data["enabledPlugins"], {"other@other": True, PLUGIN: True})
        self.assertEqual(data["otherSetting"], 42)
        self.assertFalse(any(c[0] == "codex" for c in self.calls()))

    def test_invalid_project_settings_are_not_overwritten(self):
        project = self.root / "project"
        settings = project / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text("invalid json")
        result = self.run_install("--project", str(project))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(settings.read_text(), "invalid json")
        self.assertNotIn("pinned in", result.stdout)

    def test_wiki_checks_inform_and_codex_is_told_to_trust_the_hooks(self):
        result = self.run_install("--agents", "codex")
        self.assert_ok(result)
        self.assertIn("kube context acme-prod-eu", result.stdout)
        self.assertIn("miss", result.stdout)
        self.assertIn("/hooks", result.stdout)

    def test_bootstrap_forwards_arguments(self):
        self.assert_ok(self.run_install("--agents", "codex", script=BOOTSTRAP))
        self.assertEqual(len(self.mutations()), 2)
        self.assertTrue(all(c[0] == "codex" for c in self.mutations()))

    def test_prompt_when_script_is_on_stdin(self):
        # Like curl | bash: script bytes occupy stdin, selection comes via /dev/tty.
        pid, terminal = pty.fork()
        if pid == 0:
            os.execve("/bin/bash", ["bash", "-c", 'cat "$1" | bash',
                                   "installer-test", str(INSTALL)], self.env)
        output = b""
        answered = False
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if not select.select([terminal], [], [], 0.1)[0]:
                    continue
                try:
                    chunk = os.read(terminal, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    break
                if not chunk:
                    break
                output += chunk
                if b"Choose [1/2/3]:" in output and not answered:
                    os.write(terminal, b"2\n")
                    answered = True
            else:
                self.fail("Interactive installer timed out: " + output.decode())
            _, status = os.waitpid(pid, 0)
            pid = None
            self.assertTrue(answered, output.decode())
            self.assertEqual(os.waitstatus_to_exitcode(status), 0, output.decode())
            self.assertTrue(all(c[0] == "codex" for c in self.mutations()))
            self.assertEqual(len(self.mutations()), 2)
        finally:
            os.close(terminal)
            if pid is not None:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)


if __name__ == "__main__":
    unittest.main()

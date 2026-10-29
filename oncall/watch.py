#!/usr/bin/env python3
"""On-call watch: every active alert plus the probes, deduplicated into problems.

    python3 core/oncall/watch.py --once            # one cycle, print the report, exit
    python3 core/oncall/watch.py                   # loop: a cycle every `[oncall] interval`
    python3 core/oncall/watch.py --config <wiki>/hooks/wikiloop.json --state-dir /tmp/oncall

Reads the wiki's resolved config (`hooks/wikiloop.json`, written by `wikiloop build`): by
default `$CLAUDE_PLUGIN_ROOT/hooks/wikiloop.json`, else the first `hooks/wikiloop.json` above
this script. Each cycle reads every source, folds the signals into problems, rewrites
<state-dir>/report.md and state.json, appends to events.log, and prints one line per problem
state change (NEW, REOPENED, ESCALATED, SPREAD, RESOLVED), per source failure and an hourly
HEARTBEAT, so a Monitor or a terminal sees changes, not alerts.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE))

from oncall import defaults, engine  # noqa: E402
from oncall.context import Context  # noqa: E402
from oncall.present import view_of  # noqa: E402
from oncall.sources import extensions  # noqa: E402
from wikiloop.config import merge  # noqa: E402

RESOLVED_CONFIG = Path("hooks") / "wikiloop.json"


def find_config(given: str) -> Path:
    if given:
        return Path(given).expanduser().resolve()

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root and (Path(plugin_root) / RESOLVED_CONFIG).is_file():
        return Path(plugin_root) / RESOLVED_CONFIG

    for directory in Path(__file__).resolve().parents:
        if (directory / RESOLVED_CONFIG).is_file():
            return directory / RESOLVED_CONFIG
    sys.exit("no hooks/wikiloop.json found: pass --config, or run `wikiloop build` in the wiki")


def load(path: Path) -> dict:
    """The resolved config, with defaults a build older than this core did not write."""
    cfg = json.loads(path.read_text())
    cfg["oncall"] = merge(defaults.DEFAULTS, cfg.get("oncall", {}))

    errors = defaults.validate(cfg)
    if errors:
        sys.exit("\n".join(f"{path}: {e}" for e in errors))
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="", help="the wiki's hooks/wikiloop.json")
    ap.add_argument("--once", action="store_true", help="one cycle, print the report, exit")
    ap.add_argument("--interval", type=int, help="seconds between cycles; default `[oncall] interval`")
    ap.add_argument("--resolve-after", type=int, help="absent cycles before a problem resolves, 1 or more")
    ap.add_argument("--heartbeat", type=int, help="seconds between HEARTBEAT lines, 0 for none")
    ap.add_argument("--state-dir", default="", help="default `[oncall] state_dir`, else $HOME/.cache/<plugin>/oncall")
    ap.add_argument("--alerts-only", action="store_true", help="read Alertmanager only, no probes or extensions")
    ap.add_argument("--stream-min-severity", help="stdout carries changes at this severity or above; default `[oncall] floor`")
    ap.add_argument("--kube-context", action="append", default=[], metavar="CLUSTER=CONTEXT",
                    help="read a restarted container's last error line through this kube context; repeatable")
    args = ap.parse_args()

    config_path = find_config(args.config)
    cfg = load(config_path)
    oncall = cfg["oncall"]

    if args.resolve_after is not None:
        oncall["resolve_after"] = args.resolve_after
    if args.interval is not None:
        oncall["interval"] = args.interval
    for pair in args.kube_context:
        cluster, _, context = pair.partition("=")
        oncall["restarts"]["kube_contexts"][cluster] = context

    errors = defaults.validate(cfg)
    if errors:
        sys.exit("\n".join(errors))

    ctx = Context(cfg, config_path.parent.parent)
    interval = oncall["interval"]
    heartbeat = oncall["heartbeat"] if args.heartbeat is None else args.heartbeat
    floor = ctx.rank[args.stream_min_severity or oncall["floor"]]
    presenter = extensions.load(ctx.root, oncall["presenter"]) if oncall["presenter"] else None

    default_dir = f"~/.cache/{ctx.plugin}/oncall"
    state_dir = Path(os.path.expanduser(args.state_dir or oncall["state_dir"] or default_dir))
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path, report_path, log_path = state_dir / "state.json", state_dir / "report.md", state_dir / "events.log"

    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}

    sources = engine.readers(ctx, args.alerts_only)
    last_good: dict = {}
    last_heartbeat = 0.0
    while True:
        now = time.time()
        baseline = "problems" not in state
        signals, health = engine.collect(sources, last_good)
        events = engine.advance(state, engine.fold(signals, state, ctx, now), health, ctx, now)
        report = engine.render(state, events, interval, baseline, ctx, now)

        # the screen draws `view` and never parses an alert itself
        for p in state["problems"].values():
            p["view"] = view_of(p, ctx, presenter)

        open_ = [p for p in state["problems"].values() if p["status"] == "open"]
        if baseline:
            lines = [(f"{engine.hhmm(now)} BASELINE {len(open_)} open problems ({engine.counts_line(open_, ctx)}); "
                      f"report {report_path}", True)]
        else:
            lines = engine.stream(events, state["problems"], floor, now, ctx)

        # saved after stream(), which records what stdout told
        state["interval"] = interval  # the screen's stale warning counts cycles of this length
        write(state_path, json.dumps(state))
        write(report_path, report)

        is_heartbeat_due = heartbeat and now - last_heartbeat >= heartbeat and not baseline
        if is_heartbeat_due:
            lines.append((f"{engine.hhmm(now)} HEARTBEAT {len(open_)} open ({engine.counts_line(open_, ctx)})", True))
            last_heartbeat = now
        last_heartbeat = last_heartbeat or now

        with open(log_path, "a") as log:
            log.writelines(line + "\n" for line, _ in lines)
        if args.once:
            print(report)
            return 0

        for line, shown in lines:
            if shown:
                print(line, flush=True)
        time.sleep(interval)


def write(path: Path, text: str) -> None:
    """Replace in one step: the screen polls the file and must never read half of it."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


if __name__ == "__main__":
    sys.exit(main())

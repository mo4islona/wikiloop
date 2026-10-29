"""The rails of the watch: signals fold into problems, problems change state in events, events
reach a person once.

- Dedup by subject, not by alert: every alert name on one subject and component is one problem;
  one alert name on many subjects that started together is one fleet problem.
- A problem resolves only after it was absent for `resolve_after` cycles, and only when every
  source that reported it answered. A source that fails repeats its last answer, so its problems
  freeze; it never resolves them.
- Stdout tells a flapping problem once; events.log and the report keep every change.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from oncall.context import Context
from oncall.sources import alertmanager, extensions, probes, restarts

# a restart has its own cause per pod, and its last error line is the information: never folded
NO_FLEET = set(restarts.KINDS)


def now_iso(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hhmm(ts: float) -> str:
    return time.strftime("%H:%MZ", time.gmtime(ts))


def age(seconds: float) -> str:
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def span(seconds: int) -> str:
    """A configured duration as a person writes it: 6h, 30m, 1d."""
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def section_title(section: dict, ctx: Context) -> str:
    return section["title"].replace("{resolved_kept}", span(ctx.t["resolved_kept"]))


# ---------------------------------------------------------------- sources

def readers(ctx: Context, alerts_only: bool = False) -> dict:
    """source name -> a function that reads that source's signals for one cycle."""
    out = {}
    if ctx.oncall["alertmanager"]["url"]:
        out["alertmanager"] = lambda: alertmanager.collect(ctx)
    if alerts_only:
        return out

    if ctx.probes:
        out["probes"] = lambda: probes.collect(ctx)
    if ctx.oncall["restarts"]["enabled"]:
        out["restarts"] = lambda: restarts.collect(ctx)
    for path in ctx.oncall["extensions"]:
        out[extensions.source_name(path)] = extension_reader(ctx, path)
    return out


def extension_reader(ctx: Context, path: str):
    name = extensions.source_name(path)
    loaded = {}

    def read() -> list:
        if "module" not in loaded:
            loaded["module"] = extensions.load(ctx.root, path)

        # the source name is what freezes its problems when it fails, so the engine sets it
        return [{**s, "source": name} for s in loaded["module"].collect(ctx)]
    return read


def collect(sources: dict, last_good: dict) -> tuple:
    """Signals and per-source health; a source that fails repeats its last answer, so its problems freeze."""
    signals, health = [], {}
    for source, read in sources.items():
        try:
            last_good[source] = read()
            health[source] = "ok"
        except Exception as e:
            health[source] = f"down: {e!r}"[:160]
        signals += last_good.get(source, [])
    return signals, health


# ---------------------------------------------------------------- folding

def start_ts(s: dict, default: float) -> float:
    try:
        return datetime.strptime(s["started"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return default   # probes carry no start: they all describe this cycle


def fleetwide(signals: list, open_fleets: list, ctx: Context, now: float | None = None) -> list:
    """Re-key one signal name on one component into a fleet problem where it started on many subjects together.

    Subjects are chained by start time, a gap over `fleet_gap` ending the chain; a chain of
    `fleet_min` subjects or more is a new fleet problem. Unrelated failures that share an alert
    name but started days apart stay separate, so a new one is never hidden inside an old fleet.
    An open fleet keeps its members while two of them still fire, and takes in a subject that
    started within `fleet_gap` of its latest member, so it neither dissolves nor resolves just
    because it dropped under `fleet_min`.
    """
    now = time.time() if now is None else now
    gap, minimum = ctx.t["fleet_gap"], ctx.t["fleet_min"]
    no_fleet = NO_FLEET | set(ctx.subject["no_fleet"])

    starts: dict = {}
    for s in signals:
        if s["subject"] and s["name"] not in no_fleet:
            group = starts.setdefault((s["source"], s["name"], s["component"]), {})
            group[s["subject"]] = min(group.get(s["subject"], now), start_ts(s, now))

    fleet_of = {}   # (group, subject) -> (fleet id, members)
    for key, by_subject in starts.items():
        free = dict(by_subject)
        taken_ids = set()

        for pid, group, members in open_fleets:
            if tuple(group) != key:
                continue
            kept = [n for n in members if n in free]
            if len(kept) < 2:
                continue

            latest = max(free[n] for n in kept)
            joined = [n for n in free if n not in kept and abs(free[n] - latest) <= gap]
            for subject in kept + joined:
                del free[subject]
                fleet_of[(key, subject)] = (pid, kept + joined)
            taken_ids.add(pid)

        chains, chain, last = [], [], None
        for subject, ts in sorted(free.items(), key=lambda kv: kv[1]):
            if last is not None and ts - last > gap:
                chains.append(chain)
                chain = []
            chain.append(subject)
            last = ts
        chains.append(chain)

        source, name, component = key
        for members in sorted((c for c in chains if len(c) >= minimum), key=len, reverse=True):
            pid = f"fleet/{component}/{name}"
            if pid in taken_ids:
                pid += "@" + time.strftime("%Y-%m-%dT%H:%M", time.gmtime(free[members[0]]))
            taken_ids.add(pid)
            for subject in members:
                fleet_of[(key, subject)] = (pid, members)

    out = []
    for s in signals:
        key = (s["source"], s["name"], s["component"])
        fleet = fleet_of.get((key, s["subject"]))
        if fleet:
            pid, members = fleet
            listed = ", ".join(sorted(members)[:6]) + (", ..." if len(members) > 6 else "")
            s = {**s, "id": pid, "scope": "fleet", "fleet_group": list(key),
                 "summary": f"{s['name']} on {len(members)} {ctx.subject['noun']}: {listed}"}
        out.append(s)
    return out


def fold(signals: list, state: dict, ctx: Context, now: float | None = None) -> dict:
    open_fleets = [(p["id"], p["fleet_group"], p.get("subjects", []))
                   for p in state.get("problems", {}).values()
                   if p["status"] == "open" and p.get("fleet_group")]

    problems = {}
    for s in fleetwide(signals, open_fleets, ctx, now):
        p = problems.setdefault(s["id"], {
            "id": s["id"], "scope": s["scope"], "component": s["component"], "variant": s["variant"],
            "tier": s["tier"], "env": s["env"], "severity": ctx.lowest, "signals": {}, "subjects": [],
            "fleet_group": s.get("fleet_group"),
        })
        absorb(p, s, ctx)
    return problems


def absorb(p: dict, s: dict, ctx: Context) -> None:
    # a fleet problem holds one signal per name: keep the earliest start, list every subject
    key = f"{s['source']}:{s['name']}"
    held = p["signals"].get(key)
    if held is None or (s["started"] and (not held["started"] or s["started"] < held["started"])):
        p["signals"][key] = s
    if s["subject"] and s["subject"] not in p["subjects"]:
        p["subjects"].append(s["subject"])

    # a silenced alert still describes the problem but never raises its severity
    is_higher = ctx.rank.get(s["severity"], 0) > ctx.rank[p["severity"]]
    if not s["silenced"] and is_higher:
        p["severity"] = s["severity"]
    if ctx.tier_rank.get(s["tier"], 0) > ctx.tier_rank.get(p["tier"], 0):
        p["tier"], p["env"] = s["tier"], s["env"]


def keep_unanswered(old: dict, cur: dict, health: dict, ctx: Context) -> dict:
    """`cur` plus the old signals of every source that did not answer this cycle.

    A down source repeats its last answer only while the watcher runs; after a restart it has
    none. Without this, another source's report of the same problem would replace its evidence:
    the severity would drop, and the problem would resolve while the source that saw it is down.
    """
    kept = [s for key, s in old["signals"].items()
            if key not in cur["signals"] and health.get(s["source"], "ok") != "ok"]
    if not kept:
        return cur

    merged = {**cur, "signals": dict(cur["signals"]), "subjects": list(cur["subjects"])}
    for s in kept:
        absorb(merged, s, ctx)
    return merged


def started_at(p: dict, default: float) -> float:
    """The earliest alert start among the problem's signals: a watch started late still ages it right."""
    return min([start_ts(s, default) for s in p["signals"].values()] + [default])


def advance(state: dict, current: dict, health: dict, ctx: Context, now: float | None = None) -> list:
    """Merge this cycle into the state and return its events."""
    now = time.time() if now is None else now
    t = ctx.t
    events = []
    problems = state.setdefault("problems", {})

    for pid, cur in current.items():
        old = problems.get(pid)
        if old is None or old["status"] == "resolved":
            reopened = old is not None and now - old["resolved_at"] < t["resolved_kept"]
            problems[pid] = {**cur, "status": "open", "last_seen": now, "missing": 0,
                             "first_seen": old["first_seen"] if reopened else started_at(cur, now),
                             "flaps": old["flaps"] + 1 if reopened else 0,
                             "reopened_at": now if reopened else 0,
                             "shown": old.get("shown", "") if reopened else ""}
            events.append(("REOPENED" if reopened else "NEW", problems[pid]))
            continue

        cur = keep_unanswered(old, cur, health, ctx)
        escalated = ctx.rank[cur["severity"]] > ctx.rank.get(old["severity"], 0)
        joined = set(cur["subjects"]) - set(old.get("subjects", []))
        pending = sorted((set(old.get("spread_pending", [])) | joined) & set(cur["subjects"]))
        problems[pid] = {**old, **cur, "last_seen": now, "missing": 0, "spread_pending": pending}
        p = problems[pid]

        if escalated:
            events.append(("ESCALATED", p))
        elif pending and pid.startswith("fleet/") and now - p.get("spread_at", 0) >= t["spread_every"]:
            # a subject joining a fleet problem is news even when the severity does not move;
            # a fleet growing every cycle is told once per spread_every with everything that joined
            p["spread"], p["spread_pending"], p["spread_at"] = pending, [], now
            events.append(("SPREAD", p))

    for pid, old in problems.items():
        if old["status"] != "open" or pid in current:
            continue

        unanswered = [s for s in old["signals"].values() if health.get(s["source"], "ok") != "ok"]
        if unanswered:
            continue

        old["missing"] += 1
        if old["missing"] >= ctx.oncall["resolve_after"]:
            old["status"], old["resolved_at"] = "resolved", now
            events.append(("RESOLVED", old))

    expired = [pid for pid, p in problems.items()
               if p["status"] == "resolved" and now - p["resolved_at"] > t["resolved_kept"]]
    for pid in expired:
        del problems[pid]

    # one failed cycle is usually a proxy hiccup: a source is reported down after source_down_after in a row
    known = state.setdefault("health", {})
    failures = state.setdefault("failures", {})
    reported = state.setdefault("reported_down", {})
    for source, status in health.items():
        known[source] = status
        failures[source] = 0 if status == "ok" else failures.get(source, 0) + 1

        if failures[source] >= t["source_down_after"] and not reported.get(source):
            events.append(("SOURCE-DOWN", {"id": source, "summary": status}))
            reported[source] = True
        elif status == "ok" and reported.get(source):
            events.append(("SOURCE-UP", {"id": source, "summary": status}))
            reported[source] = False
    return events


# ---------------------------------------------------------------- output

def headline(p: dict) -> str:
    signals = list(p["signals"].values())

    # the alert's sentence first, then what the probes add (a restart's last error line)
    alerts = [s["summary"] for s in signals if s["source"] == "alertmanager"][:1]
    others = [s["summary"] for s in signals if s["source"] != "alertmanager"]
    summary = " · ".join(dict.fromkeys(alerts + others))

    names = ", ".join(sorted({s["name"] + (" (silenced)" if s.get("silenced") else "") for s in signals}))
    tier = f", {p['tier']}/{p['env']}" if p["tier"] != "-" else ""
    return f"{p['id']} [{p['severity']}{tier}]: {summary} ({names})"


def event_line(kind: str, p: dict, now: float) -> str:
    if kind.startswith("SOURCE"):
        return f"{hhmm(now)} {kind} {p['id']}: {p['summary']}"
    if kind == "REOPENED":
        return f"{hhmm(now)} {kind} (flap #{p['flaps']}) {headline(p)}"
    if kind == "SPREAD":
        added = ", ".join(p["spread"][:8]) + (f" and {len(p['spread']) - 8} more" if len(p["spread"]) > 8 else "")
        return f"{hhmm(now)} {kind} +{added} to {headline(p)}"
    return f"{hhmm(now)} {kind} {headline(p)}"


def tell(kind: str, p: dict, now: float, ctx: Context) -> bool:
    """Whether stdout carries this change of a loud problem; records what stdout then says about it.

    `shown` is the problem as stdout last told it. A flapping problem would repeat the same
    REOPENED and RESOLVED pair every few cycles, so stdout drops a line that tells an open state it
    already told, and holds a RESOLVED that follows a REOPENED closely: the stream never ends on a
    resolve that the next cycle takes back.
    """
    if kind == "SPREAD":
        return True

    if kind == "RESOLVED":
        reopened_at = p.get("reopened_at", 0)
        is_flapping = reopened_at > 0 and now - reopened_at < ctx.t["flap_quiet"]
        if is_flapping:
            return False
        p["shown"] = "resolved"
        return True

    told, _, told_severity = p.get("shown", "").partition(":")
    told_rank = ctx.rank.get(told_severity, 0) if told == "open" else 0
    if told_rank >= ctx.rank[p["severity"]]:
        return False

    p["shown"] = f"open:{p['severity']}"
    return True


def stream(events: list, problems: dict, floor: int, now: float, ctx: Context) -> list:
    """(line, shown on stdout) for this cycle: every event, then the RESOLVED lines tell() held back."""
    lines = []
    for kind, p in events:
        if kind.startswith("SOURCE"):
            lines.append((event_line(kind, p, now), True))
            continue

        is_loud = ctx.rank.get(p["severity"], 0) >= floor
        lines.append((event_line(kind, p, now), is_loud and tell(kind, p, now, ctx)))

    quiet = ctx.t["flap_quiet"]
    for p in problems.values():
        is_settled = (p["status"] == "resolved" and p.get("shown", "").startswith("open")
                      and now - p["resolved_at"] >= quiet)
        if is_settled:
            p["shown"] = "resolved"
            lines.append((f"{hhmm(now)} RESOLVED (away for {age(quiet)}) {headline(p)}", True))
    return lines


def counts_line(open_: list, ctx: Context) -> str:
    counts: dict = {}
    for p in open_:
        counts[p["severity"]] = counts.get(p["severity"], 0) + 1
    return " · ".join(f"{counts.get(s, 0)} {s}" for s in ctx.severities)


def sort_key(p: dict, ctx: Context) -> tuple:
    is_other_env = p["env"] not in ("-", ctx.subject["default_env"])
    return (-ctx.rank.get(p["severity"], 0), -ctx.tier_rank.get(p["tier"], 0), is_other_env, p["first_seen"])


def is_chronic(p: dict, ctx: Context, now: float) -> bool:
    return p["status"] == "open" and now - p["first_seen"] >= ctx.t["chronic_after"]


def is_new(p: dict, ctx: Context, now: float) -> bool:
    is_told = ctx.rank.get(p["severity"], 0) >= ctx.floor
    return p["status"] == "open" and is_told and now - p["first_seen"] < ctx.t["new_window"]


def in_section(p: dict, section: dict, ctx: Context, now: float, below_floor: bool = False) -> bool:
    """The pane's filter, the same in the mod: status, severity range, chronic, new."""
    if p["status"] != section["status"]:
        return False

    rank = ctx.rank.get(p["severity"], 0)
    is_below = bool(section["min_severity"]) and rank < ctx.rank[section["min_severity"]]
    if is_below != below_floor:
        return False
    if section["max_severity"] and rank > ctx.rank[section["max_severity"]]:
        return False

    for key, flag in (("chronic", is_chronic(p, ctx, now)), ("new", is_new(p, ctx, now))):
        if section[key] == "only" and not flag:
            return False
        if section[key] == "exclude" and flag:
            return False
    return True


def bullet(p: dict, when: str) -> str:
    """One problem as one line: the subject in bold, then severity, tier, what is wrong and since when."""
    rest = headline(p).split(" [", 1)[1]
    return f"- **{p['id']}** [{rest} · {when}"


def render(state: dict, events: list, interval: int, baseline: bool, ctx: Context, now: float | None = None) -> str:
    now = time.time() if now is None else now
    problems = sorted(state["problems"].values(), key=lambda p: sort_key(p, ctx))
    open_ = [p for p in problems if p["status"] == "open"]

    def since(p: dict) -> str:
        flaps = f", {p['flaps']} flaps" if p.get("flaps") else ""
        return f"since {hhmm(p['first_seen'])} ({age(now - p['first_seen'])}{flaps})"

    def when(p: dict, section: dict) -> str:
        if p["status"] == "resolved":
            return f"resolved {hhmm(p['resolved_at'])}, open {age(p['resolved_at'] - p['first_seen'])}"
        if section["chronic"] == "only":
            return age(now - p["first_seen"])
        return since(p)

    lines = [
        f"# On-call report, {now_iso(now)}",
        "",
        f"Cycle every {age(interval)}; a report older than two cycles is no evidence of health.",
        f"Open: {counts_line(open_, ctx)}. Sources: " + ", ".join(f"{k} {v}" for k, v in state["health"].items()),
        "",
        "## New and changed this cycle",
        "",
    ]
    if baseline:
        lines.append("- first cycle: everything open is listed below")
    else:
        lines += [f"- {event_line(kind, p, now)}" for kind, p in events] or ["- none"]

    listed = set()
    for section in ctx.sections:
        members = [p for p in problems if in_section(p, section, ctx, now)]
        listed |= {p["id"] for p in members}

        lines += ["", f"## {section_title(section, ctx)}", ""]
        lines += [bullet(p, when(p, section)) for p in members] or ["- none"]

        folded = [p for p in problems if section["fold_below"] and in_section(p, section, ctx, now, below_floor=True)]
        if folded:
            lines.append(f"- and {len(folded)} more below {section['min_severity']}")

    others = [p for p in open_ if p["id"] not in listed]
    lines += ["", "## Other open problems", ""]
    lines += [bullet(p, since(p)) for p in others] or ["- none"]
    return "\n".join(lines) + "\n"

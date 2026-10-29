"""Every container restart in the window, with why it ended and, given a kube context, its last
error line.

Restart rules wait for a pattern before they fire; this reports the first restart, so a one-off
crash and the start of a loop are visible while the rules are still pending. Reads
kube-state-metrics through `[oncall.prometheus]`. Several pods that restart once on one node
are one node problem: a node event restarts everything on it at once.
"""
from __future__ import annotations

import json
import re
import subprocess

from oncall.context import Context

KINDS = ("crash-loop", "oom-killed", "restarted", "node-restarts")
KUBECTL_NOTICE = re.compile(r"^(unable to retrieve container logs|previous terminated container|Error from server)", re.I)
ERROR_LINE = re.compile(r'"level":\s*(5|"?(error|fatal)"?)|\bERROR\b|panic|Traceback|Exception', re.I)

LOG_CACHE: dict = {}   # (context, namespace, pod, container, restart count) -> last error line


def collect(ctx: Context) -> list:
    table = ctx.oncall["restarts"]
    window = table["window"]
    selector = f'namespace!~"{table["exclude_namespaces"]}"' if table["exclude_namespaces"] else ""
    cluster = table["cluster_label"]

    restarted = ctx.query(f"sum by ({cluster}, namespace, pod, container) "
                         f"(increase(kube_pod_container_status_restarts_total{{{selector}}}[{window}])) >= 1")
    totals = by_container(ctx.query(f"max by (namespace, pod, container) "
                                    f"(kube_pod_container_status_restarts_total{{{selector}}})"))
    reasons = by_container(ctx.query(f"max by (namespace, pod, container, reason) "
                                     f"(kube_pod_container_status_last_terminated_reason{{{selector}}}) > 0"), "reason")
    exit_codes = by_container(ctx.query(f"max by (namespace, pod, container) "
                                        f"(kube_pod_container_status_last_terminated_exitcode{{{selector}}})"))
    node_of = {(m["metric"].get("namespace", ""), m["metric"].get("pod", "")): m["metric"].get("node", "")
               for m in ctx.query(f"max by (namespace, pod, node) (kube_pod_info{{{selector}}})")}

    out = []
    once_by_node: dict = {}
    for series in restarted:
        labels = dict(series["metric"])
        namespace, pod, container = labels.get("namespace", ""), labels.get("pod", ""), labels.get("container", "")
        key = (namespace, pod, container)
        count = round(float(series["value"][1]))
        reason = reasons.get(key, "")

        kind = "crash-loop" if count >= table["crash_loop_after"] else "oom-killed" if reason == "OOMKilled" else "restarted"
        subject = ctx.subject_of(labels)
        tier = ctx.tier_env(subject, labels)[0] if subject else ctx.default_tier
        severity = ctx.severity_for(table["severity"].get(kind, ctx.lowest), tier)

        detail = f"{reason or 'unknown reason'}, exit {int(exit_codes[key]) if key in exit_codes else '?'}"
        context = table["kube_contexts"].get(labels.get(cluster, ""))
        if context:
            line = last_error_line(context, namespace, pod, container, int(totals.get(key, count)))
            detail += f": {line}" if line else ""

        s = ctx.signal(labels, container or "pod", severity, "restarts", kind,
                       f"{namespace}/{pod} restarted {count}x in {window} ({detail})")
        if kind == "crash-loop":
            out.append(s)
        else:
            once_by_node.setdefault(node_of.get((namespace, pod), ""), []).append((s, f"{namespace}/{pod} ({reason or '?'})"))

    for node, restarts in once_by_node.items():
        if not node or len(restarts) < table["node_min"]:
            out += [s for s, _ in restarts]
            continue

        listed = ", ".join(sorted(p for _, p in restarts)[:6]) + (", ..." if len(restarts) > 6 else "")
        s = ctx.signal({}, "node", ctx.lowest, "restarts", "node-restarts",
                       f"{len(restarts)} pods restarted once on {node} in {window}: {listed}")
        out.append({**s, "id": f"node/{node}", "scope": node})
    return out


def by_container(series: list, label: str = "") -> dict:
    """(namespace, pod, container) -> the series value, or the value of `label`."""
    out = {}
    for m in series:
        metric = m["metric"]
        key = (metric.get("namespace", ""), metric.get("pod", ""), metric.get("container", ""))
        out[key] = metric.get(label, "") if label else float(m["value"][1])
    return out


def redact(line: str) -> str:
    """Log lines carry URLs with keys in their path or query: keep scheme and host only."""
    line = re.sub(r"(https?://[^/\s\"']+)[^\s\"']*", r"\1/<redacted>", line)
    return re.sub(r"(?i)((?:api[-_]?key|secret|token|password)[\"']?\s*[=:]\s*[\"']?)[^\s\"'&,}]+", r"\1<redacted>", line)


def readable(line: str) -> str:
    """A JSON log line reduced to its message and the first line of its error."""
    try:
        entry = json.loads(line)
    except ValueError:
        return line
    if not isinstance(entry, dict):
        return line

    fields = entry.get("fields") if isinstance(entry.get("fields"), dict) else {}
    message = entry.get("msg") or entry.get("message") or fields.get("message") or ""
    err = entry.get("err") or entry.get("error") or fields.get("error") or ""
    if isinstance(err, dict):
        err = err.get("stack") or err.get("message") or json.dumps(err)

    err = str(err).splitlines()[0] if err else ""
    return ": ".join(part for part in (message, err) if part) or line


def last_error_line(context: str, namespace: str, pod: str, container: str, restarts: int) -> str:
    key = (context, namespace, pod, container, restarts)
    if key in LOG_CACHE:
        return LOG_CACHE[key]

    try:
        logs = subprocess.run(["kubectl", "--context", context, "-n", namespace, "logs", pod, "-c", container,
                               "--previous", "--tail", "200"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        logs = ""

    # when the previous container's log is gone, the API answers with its own sentence as the log
    lines = [l for l in logs.splitlines() if l.strip() and not KUBECTL_NOTICE.match(l)]
    errors = [l for l in lines if ERROR_LINE.search(l)]
    line = redact(readable((errors or lines or [""])[-1]))[:240]

    LOG_CACHE[key] = line
    return line

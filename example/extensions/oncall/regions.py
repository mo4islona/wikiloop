"""ACME: a region that took over the traffic of the others.

Failover keeps every service answering, so no rule fires; the region that took the load runs
without a spare. This source names a region that carries more than its share of requests.
"""
SHARE = 0.8
TRAFFIC = ("sum by (region) (rate(acme_requests_total[10m]))"
           " / scalar(sum(rate(acme_requests_total[10m])))")


def collect(ctx) -> list:
    out = []
    for series in ctx.query(TRAFFIC):
        region = series["metric"].get("region", "?")
        share = float(series["value"][1])
        if share <= SHARE:
            continue

        summary = f"{region} serves {share:.0%} of requests: the other regions dropped out"
        out.append(ctx.signal({"region": region}, "traffic", "minor", "ext", "region-failover", summary))
    return out

# Checkout incidents

Grep-first file: `grep -n '^## ' incidents.md` lists the entries; read one.

## 2026-09-14 — checkout slow in prod-eu only
**Symptom:** p99 checkout latency rose in `prod-eu`; `prod-us` was flat.
**Root cause:** the payments connection pool in `prod-eu` was full after a provider slowdown.
**Fix:** the payments team raised the pool size in its values file.
**Lesson:** latency in one cluster only points at a per-cluster dependency first.

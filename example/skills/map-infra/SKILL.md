---
name: map-infra
description: >-
  Where ACME infrastructure lives: the prod-eu, prod-us and staging clusters, kube contexts, namespaces, deploy tools, alert routing. Read first for "where does X run", "which kube context", or a silent alert.
owner: ops-team
last-verified: 2026-10-20
sources:
  - https://github.com/acme/infra/tree/main/clusters
---

# Where infrastructure lives

Answers "where does X run, how does it get there, and who hears when it breaks".

## Invariants

- Production runs in two clusters, `prod-eu` and `prod-us`, with the same namespaces; a
  service that is healthy in one can be down in the other, so always name the cluster.
- `staging` shares the payment provider's sandbox with every developer laptop: a rate limit
  there is never a staging outage.
- Deploys go through the `deploy` pipeline of each service repo; a manual `kubectl apply` is
  reverted by the next sync within minutes.

## What to read

| Reading | For |
|---|---|
| [clusters.md](references/clusters.md) | which cluster, which kube context, which namespace |

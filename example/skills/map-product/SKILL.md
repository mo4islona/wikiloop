---
name: map-product
description: >-
  Map of what ACME ships: checkout, payments, search; which repo owns each, where it runs, who owns it. Ask it "what is X", "which repo", "who owns".
owner: ops-team
last-verified: 2026-10-20
sources:
  - https://github.com/acme/checkout
---

# What ships and who owns it

| Product | Repo | Runs in | Debug skill |
|---|---|---|---|
| Checkout | `acme/checkout` | `prod-eu`, `prod-us` | [debug-checkout](../debug-checkout/SKILL.md) |
| Payments | `acme/payments` | `prod-eu` | none yet |
| Search | `acme/search` | `prod-eu`, `prod-us` | none yet |

## Invariants

- Checkout calls payments synchronously; a payments stall shows first as checkout latency.

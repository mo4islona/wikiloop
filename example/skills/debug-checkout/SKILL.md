---
name: debug-checkout
description: >-
  Debug the ACME checkout service: slow or failed orders, 502s, stuck carts, payment timeouts. Use for "checkout is slow", "orders fail", "502 on checkout".
owner: shop-team
last-verified: 2026-10-20
sources:
  - https://github.com/acme/checkout/tree/main/deploy
---

# Debug checkout

Answers "why are orders slow or failing". Checkout is one service in each production cluster;
it holds no state of its own and waits on payments for every order.

## Invariants

- p99 latency that rises in one cluster only is a payments problem in that cluster, not a
  checkout one: check payments before you restart checkout.
- A 502 from the edge with no error in checkout's log means the pod was killed mid-request;
  look at restarts, not at the code.
- `checkout_orders_failed_total` counts declined cards too; a rise with a flat
  `payments_errors_total` is customers, not us.

## What to read

| Reading | For |
|---|---|
| [latency.md](references/latency.md) | slow orders: which series, in what order |
| [incidents.md](references/incidents.md) | grep-first; past incidents by symptom |

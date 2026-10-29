# Clusters

| Cluster | Kube context | Role |
|---|---|---|
| `prod-eu` | `acme-prod-eu` | production, Europe; the primary for payments |
| `prod-us` | `acme-prod-us` | production, Americas |
| `staging` | `acme-staging` | pre-release; shares sandboxes with laptops |

Namespaces follow the service name (`checkout`, `payments`, `search`) in every cluster.

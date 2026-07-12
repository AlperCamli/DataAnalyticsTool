---
doc_class: machine-group
objects:
  - { object: "ga4.custom.calcMetric:revenue_per_user", kind: api_metric, schema_hash: "sha256:a3c5d147e153a79819b7bb34f98bd853e923b74d2c34f5e275965e1bf6d22f1e" }
  - { object: "ga4.custom.customEvent:support_tickets", kind: api_metric, schema_hash: "sha256:f7bb3e5b6743c7599a47b817ca362a18eb362702fe7d4e3f0f1380826cdc1e14" }
  - { object: "ga4.standard.activeUsers", kind: api_metric, schema_hash: "sha256:fcebb45cf4555d5cd4540c217b0ec521f2498f3e936796270d321df891f187f4" }
  - { object: "ga4.standard.sessions", kind: api_metric, schema_hash: "sha256:c212a9134cf2eb4a24629c481de9c9070dfde9e833543e4a07d2bb2b2f62a38a" }
  - { object: "ga4.standard.totalRevenue", kind: api_metric, schema_hash: "sha256:67a86e18cf083feee09228b82bdc7451438aa432b7c7412a0cd5ff33bfdc7cbe" }
generated_at: 2026-07-11
source_mode: api
snapshot_version: "1"
status: machine
---

# ga4 — metrics

5 objects.

## <a id="custom--calcmetric-revenue_per_user"></a>`calcMetric:revenue_per_user`

| Fact | Value |
|---|---|
| Object | `ga4.custom.calcMetric:revenue_per_user` |
| Kind | api_metric |
| Namespace | custom |
| Data type | TYPE_CURRENCY |
| Formula | `totalRevenue/activeUsers` |
| Schema hash | `sha256:a3c5d147e153a79819b7bb34f98bd853e923b74d2c34f5e275965e1bf6d22f1e` |

Calculated metric: total revenue divided by active users.

## <a id="custom--customevent-support_tickets"></a>`customEvent:support_tickets`

| Fact | Value |
|---|---|
| Object | `ga4.custom.customEvent:support_tickets` |
| Kind | api_metric |
| Namespace | custom |
| Data type | TYPE_INTEGER |
| Scope | EVENT |
| Schema hash | `sha256:f7bb3e5b6743c7599a47b817ca362a18eb362702fe7d4e3f0f1380826cdc1e14` |

Count of support tickets opened from the in-app widget.

## <a id="standard--activeusers"></a>`activeUsers`

| Fact | Value |
|---|---|
| Object | `ga4.standard.activeUsers` |
| Kind | api_metric |
| Namespace | standard |
| Data type | TYPE_INTEGER |
| Schema hash | `sha256:fcebb45cf4555d5cd4540c217b0ec521f2498f3e936796270d321df891f187f4` |

The number of distinct users who visited your site or app.

## <a id="standard--sessions"></a>`sessions`

| Fact | Value |
|---|---|
| Object | `ga4.standard.sessions` |
| Kind | api_metric |
| Namespace | standard |
| Data type | TYPE_INTEGER |
| Schema hash | `sha256:c212a9134cf2eb4a24629c481de9c9070dfde9e833543e4a07d2bb2b2f62a38a` |

The number of sessions that began on your site or app.

## <a id="standard--totalrevenue"></a>`totalRevenue`

| Fact | Value |
|---|---|
| Object | `ga4.standard.totalRevenue` |
| Kind | api_metric |
| Namespace | standard |
| Data type | TYPE_CURRENCY |
| Schema hash | `sha256:67a86e18cf083feee09228b82bdc7451438aa432b7c7412a0cd5ff33bfdc7cbe` |

The sum of revenue from purchases, subscriptions, and advertising.

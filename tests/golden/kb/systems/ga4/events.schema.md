---
doc_class: machine-group
objects:
  - { object: "ga4.custom.plan_upgraded", kind: api_event, schema_hash: "sha256:b1587465edc46aacf62cb11097e2cb5cb0cb4a0938b5ea15d16c4b8377f7342b" }
  - { object: "ga4.custom.sign_up_completed", kind: api_event, schema_hash: "sha256:6f2466add0fde754c25d3dcd8121c19b90134594433c9eed357cb9681384363f" }
  - { object: "ga4.standard.page_view", kind: api_event, schema_hash: "sha256:26af3d54759dd2a2b763d20ea1b71cd7df5853f06847cb5c5997197e64ebba0a" }
  - { object: "ga4.standard.purchase", kind: api_event, schema_hash: "sha256:27aeac1f752ea342f1f85b5482c606402e8b0c1128e291abd68e41919bb363d7" }
  - { object: "ga4.standard.session_start", kind: api_event, schema_hash: "sha256:5ef598a7a92de92e86a5f6987dbb4ea850ae3c079af1ef67746d21f585ba6942" }
generated_at: 2026-07-11
source_mode: api
snapshot_version: "1"
status: machine
---

# ga4 — events

5 objects.

## <a id="custom--plan_upgraded"></a>`plan_upgraded`

| Fact | Value |
|---|---|
| Object | `ga4.custom.plan_upgraded` |
| Kind | api_event |
| Namespace | custom |
| Key event | false |
| Schema hash | `sha256:b1587465edc46aacf62cb11097e2cb5cb0cb4a0938b5ea15d16c4b8377f7342b` |
| Purpose | — |

## <a id="custom--sign_up_completed"></a>`sign_up_completed`

| Fact | Value |
|---|---|
| Object | `ga4.custom.sign_up_completed` |
| Kind | api_event |
| Namespace | custom |
| Key event | true |
| Schema hash | `sha256:6f2466add0fde754c25d3dcd8121c19b90134594433c9eed357cb9681384363f` |
| Purpose | — |

Sent when onboarding finishes.

## <a id="standard--page_view"></a>`page_view`

| Fact | Value |
|---|---|
| Object | `ga4.standard.page_view` |
| Kind | api_event |
| Namespace | standard |
| Key event | false |
| Schema hash | `sha256:26af3d54759dd2a2b763d20ea1b71cd7df5853f06847cb5c5997197e64ebba0a` |
| Purpose | — |

Fires on every page load or history state change.

## <a id="standard--purchase"></a>`purchase`

| Fact | Value |
|---|---|
| Object | `ga4.standard.purchase` |
| Kind | api_event |
| Namespace | standard |
| Key event | true |
| Schema hash | `sha256:27aeac1f752ea342f1f85b5482c606402e8b0c1128e291abd68e41919bb363d7` |
| Purpose | — |

A purchase was completed.

Parameters:

| # | Parameter | Type | Nullable | Default | Description |
|---|---|---|---|---|---|
| 1 | `transaction_id` | `string` | true | — | The unique identifier of the transaction. |
| 2 | `value` | `number` | true | — | The monetary value of the event. |
| 3 | `currency` | `string` | true | — | Currency of the event, in 3-letter ISO 4217 format. |

## <a id="standard--session_start"></a>`session_start`

| Fact | Value |
|---|---|
| Object | `ga4.standard.session_start` |
| Kind | api_event |
| Namespace | standard |
| Key event | false |
| Schema hash | `sha256:5ef598a7a92de92e86a5f6987dbb4ea850ae3c079af1ef67746d21f585ba6942` |
| Purpose | — |

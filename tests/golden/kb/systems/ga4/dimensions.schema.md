---
doc_class: machine-group
objects:
  - { object: "ga4.custom.customEvent:plan_tier", kind: api_dimension, schema_hash: "sha256:98215b98b375fed80a438f7126ff46a401700bc62311e4f7bb7bd65e3faf807f" }
  - { object: "ga4.custom.customUser:crm_id", kind: api_dimension, schema_hash: "sha256:990a864b3ccfde13a7b4e3003f7237a7779335c4a2efcee77c855f98a4b5a5bb" }
  - { object: "ga4.standard.country", kind: api_dimension, schema_hash: "sha256:55919ee17ec1d72c8388b42800e3c3de2ab9dbfe67873401c50667e9211f0038" }
  - { object: "ga4.standard.date", kind: api_dimension, schema_hash: "sha256:f6fe2ccc543ab7ff53f94e6016e5aa7b95b8011268779f5fc6685c66d0ad2404" }
  - { object: "ga4.standard.deviceCategory", kind: api_dimension, schema_hash: "sha256:cc41193261a64d991063c42ca746ba88c73fb847e30d74a1ca65c3d1d717a3e8" }
generated_at: 2026-07-11
source_mode: api
snapshot_version: "1"
status: machine
---

# ga4 — dimensions

5 objects.

## <a id="custom--customevent-plan_tier"></a>`customEvent:plan_tier`

| Fact | Value |
|---|---|
| Object | `ga4.custom.customEvent:plan_tier` |
| Kind | api_dimension |
| Namespace | custom |
| Data type | string |
| Schema hash | `sha256:98215b98b375fed80a438f7126ff46a401700bc62311e4f7bb7bd65e3faf807f` |
| Purpose | — |

Subscription tier attached to checkout events.

## <a id="custom--customuser-crm_id"></a>`customUser:crm_id`

| Fact | Value |
|---|---|
| Object | `ga4.custom.customUser:crm_id` |
| Kind | api_dimension |
| Namespace | custom |
| Data type | string |
| Schema hash | `sha256:990a864b3ccfde13a7b4e3003f7237a7779335c4a2efcee77c855f98a4b5a5bb` |
| Purpose | — |

CRM identifier synced from the sales pipeline.

## <a id="standard--country"></a>`country`

| Fact | Value |
|---|---|
| Object | `ga4.standard.country` |
| Kind | api_dimension |
| Namespace | standard |
| Data type | string |
| Schema hash | `sha256:55919ee17ec1d72c8388b42800e3c3de2ab9dbfe67873401c50667e9211f0038` |
| Purpose | — |

The country from which the user activity originated.

## <a id="standard--date"></a>`date`

| Fact | Value |
|---|---|
| Object | `ga4.standard.date` |
| Kind | api_dimension |
| Namespace | standard |
| Data type | string |
| Schema hash | `sha256:f6fe2ccc543ab7ff53f94e6016e5aa7b95b8011268779f5fc6685c66d0ad2404` |
| Purpose | — |

The date of the event, formatted as YYYYMMDD.

## <a id="standard--devicecategory"></a>`deviceCategory`

| Fact | Value |
|---|---|
| Object | `ga4.standard.deviceCategory` |
| Kind | api_dimension |
| Namespace | standard |
| Data type | string |
| Schema hash | `sha256:cc41193261a64d991063c42ca746ba88c73fb847e30d74a1ca65c3d1d717a3e8` |
| Purpose | — |

The type of device: Desktop, Tablet, or Mobile.

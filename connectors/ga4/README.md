# ga4 connector

Google Analytics 4 `MetadataProvider` (task 1.3, plan §3.2). One mode
(`api`), five read-only GETs against one property, plain REST via
google-auth (DECISIONS.md D-22 — no generated client libraries).

## Surfaces → objects (D-23..D-25)

| Surface | Contributes |
|---|---|
| Data API `properties/{id}/metadata` | The queryable estate: every standard + custom dimension and metric. Owns `name` (= `apiName`, verbatim, prefix included), `description`, metric `stats.data_type` (= `type`, verbatim `TYPE_*` string) |
| Admin `customDimensions` | Join/consistency only — dimension scope already rides the apiName prefix (`customEvent:`/`customUser:`/`customItem:`), so no stats field is emitted for it |
| Admin `customMetrics` | `stats.scope` for custom metrics |
| Admin v1alpha `calculatedMetrics` | `stats.formula` for calculated metrics (`calcMetric:{id}`); v1alpha because calculated metrics have not graduated to v1beta |
| Admin `keyEvents` | The `api_event` objects: `schema` from the key event's own `custom` flag (`standard`/`custom`, D-5 origin-namespace reading), `stats.is_key_event: true` |
| Admin `properties/{id}` | `source_properties` (below) |

One object per definition: custom entries appear on both the Data API
and Admin surfaces and are merged, never duplicated. A custom
definition present on one surface but not the other is a torn read →
`source_unavailable` (retryable), nothing emitted (S-6).

Dimensions carry `stats.data_type: "string"` — the Data API types every
dimension value as a string; the field is the API's own type system,
not a synthesized fact (D-24). Metric `data_type` keeps the verbatim
wire enum (`TYPE_INTEGER`, `TYPE_CURRENCY`, …).

**Events are key events only** (D-25): GA4 has no metadata API that
enumerates all events, and enumerating them via `runReport` would be a
data pull (out of scope). Consequences: `is_key_event` is always
`true`; deleting a key event surfaces as `removed` (breaking), not a
flag flip; event parameters are not introspectable → `columns: []`;
key events carry no description → `null` (S-8).

## Descriptions

Verbatim or null (S-8): the API omits empty strings (proto3 JSON), so
an absent/empty `description` is emitted as `null`. Nothing is ever
copied from Google documentation.

## Quota (J-5, D-28)

The manifest declares `rate_limit: {strategy: token-bucket, …}`,
honored by the SDK quota primitives: requests are paced by a token
bucket; 429/`RESOURCE_EXHAUSTED` responses get jittered exponential
backoff (`max_retries`); if still throttled, the job **defers** with
`retry_after_s` from the `Retry-After` header (else
`default_retry_after_s`) — a deferral never consumes a retry attempt
and never dead-letters. Every other failure maps to the §6.7 taxonomy
with no fallback (MP-1/CC-2): 401/403 → `auth_error`, 400/404 →
`config_error`, 5xx/network → `source_unavailable`. On any failure
nothing is written.

## Config

See `config.schema.json` / `config.example.json`. `system`, `mode:
"api"`, `property_id` (numeric), and exactly one credential
*reference*: `credentials_file` (path to the service-account JSON key)
or `credentials_env` (env var holding the key JSON) — key material
never lives in config files, mirroring the postgres `dsn_env` pattern.
Vault-referenced credentials arrive with the job transport (D-14).
Error messages never echo key material (JC-8). Required source-side
access: the service account added to the GA4 property with Viewer
access (`analytics.readonly` scope).

## Documented `source_properties` keys (MP-2, additive only)

| Key | Source | Why carried |
|---|---|---|
| `property_id` | Admin property `name` (`properties/313459823`) | Stable identifier for all cross-references |
| `display_name` | `displayName` | Human anchor for KB docs / Connections UI |
| `time_zone` | `timeZone` | Semantics of every date/hour dimension; needed to align GA4 with GSC/Postgres in blends |
| `currency_code` | `currencyCode` | Unit of every `TYPE_CURRENCY` metric — wrong currency in docs is S-2's "contradict human docs" case |

## Deliberate exclusions (D-26)

Archived custom definitions vanish from both API surfaces → diff
`removed` (breaking; correct — dependents do break). Dropped at the
boundary, recorded as register-item candidates where valuable:
`KeyEvent.countingMethod` (strongest candidate — changes what the
count *means*, would be hash-included), `deprecatedApiNames`. Dropped
as UI/derived noise: `uiName`, `category`, custom-metric
`measurementUnit` (already reflected in `type`),
`restrictedMetricType`, `blockedReasons`, `disallowAdsPersonalization`,
key-event `defaultValue`/`createTime`/`deletable`.

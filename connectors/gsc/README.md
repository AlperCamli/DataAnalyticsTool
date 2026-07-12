# gsc connector

Google Search Console `MetadataProvider` (task 1.4, plan §3.3). One
mode (`api`), one read-only GET (`sites.get` on the configured
property), plain REST via google-auth — the D-22 dependency footprint,
no new dependency and no generated client (DECISIONS.md D-29).

## The fixed schema (D-30)

Search Console exposes no metadata endpoint: the queryable schema is a
fixed part of the Search Analytics API itself. The estate is therefore
a constant table — six `api_dimension` (`query`, `page`, `country`,
`device`, `date`, `searchAppearance`) and four `api_metric` (`clicks`,
`impressions`, `ctr`, `position`) objects, `schema: "standard"` for
all (GSC has no custom definitions, so the standard group is total).
Names are the wire vocabulary verbatim: dimension request values and
metric response fields of `searchanalytics.query`. Provenance:
<https://developers.google.com/webmaster-tools/v1/searchanalytics/query>.

`stats.data_type` is the connector's declared vocabulary
`{string, integer, double}` (hash-included per §4.5): every dimension
value is a string; `clicks`/`impressions` are counts (`integer`);
`ctr`/`position` are a ratio and an average (`double`). The wire JSON
types all four metrics as `number` — the semantic reading is the
declared convention, pinned by the 1.1 fixture (`fixtures/gsc.json`),
whose object hashes the connector reproduces exactly.

Because the whole structural projection is constant, every
`schema_hash` is effectively immutable: it moves only when this
constant table is deliberately changed (Google changing the documented
surface ⇒ a connector release), which the diff correctly classifies as
structural/breaking.

## Descriptions

`null`, always (S-8, D-30): the fixed dimensions and metrics are
defined only in Google's reference documentation — prose that never
crosses any wire is not a snapshot fact, and nothing is ever copied
from Google documentation (the GA4 D-25 line). The human-facing
definitions belong to the generator's GSC template (task 1.5). The
description strings in `fixtures/gsc.json` are hand-authored 1.1
artifacts (D-7); a real pull cannot produce them.

## Documented `source_properties` keys (MP-2, additive only)

| Key | Source | Why carried |
|---|---|---|
| `properties` | `sites.get` on the configured property | List (exactly one entry in v1) — the property list the task exit requires, list-shaped so a future multi-property configuration stays additive |
| `properties[].site_url` | `siteUrl`, verbatim | The property identity every cross-reference uses (`sc-domain:…` or URL-prefix form) |
| `properties[].permission_level` | `permissionLevel`, verbatim | What the service account may see; `siteRestrictedUser` explains missing data before anyone debugs queries |
| `properties[].verified` | derived: `permissionLevel != "siteUnverifiedUser"` | The plan's "verified state" fact (always `true` in an emitted snapshot — unverified fails the job) |
| `data_freshness` | `data_states`: the Search Analytics `dataState` request vocabulary (`all`, `final`) | The structured fact behind plan §3.3's "data freshness notes": an agent must know fresh-but-provisional rows are requestable with `dataState=all`; the prose semantics of freshness belong to the generator template (S-8) |

One system = one property (D-31, mirroring GA4's D-27): the connector
calls `sites.get`, not `sites.list` — emitting every site the service
account can see would make snapshot content depend on unrelated grants
and leak other properties into a customer-visible KB. A customer with
several GSC properties configures several systems.

## Failure taxonomy (D-32)

Unverified property (`permissionLevel: siteUnverifiedUser`) →
`source_unavailable` (retryable: verification is source-side state a
retry can find fixed). 401/403 → `auth_error` (re-auth/re-grant flow);
400/404 → `config_error` (wrong `site_url`); 429 (or
403+`RESOURCE_EXHAUSTED`) → jittered backoff (`max_retries`), then a
J-5 **deferral** with `retry_after_s` from the `Retry-After` header
(else `default_retry_after_s`); 5xx/network → same backoff, then
`source_unavailable`. On any failure the job fails and nothing is
written (S-6). Error messages carry the endpoint path, HTTP status,
and API `status` string only (JC-8).

## Config

See `config.schema.json` / `config.example.json`. `system`, `mode:
"api"`, `site_url` (the property exactly as registered:
`sc-domain:example.com` or URL-prefix with trailing slash), and
exactly one credential *reference*: `credentials_file` or
`credentials_env` — key material never lives in config files,
mirroring the postgres `dsn_env` pattern; vault-referenced credentials
arrive with the job transport (D-14). Required source-side access: the
service account added as a user of the property (`webmasters.readonly`
scope).

## Deliberate exclusions

Dropped at the boundary, recorded here per the D-18 pattern (no
register items proposed — none passes the S-2 test yet): the
`sites.list` estate beyond the configured property (see D-31); the
hourly surface (`dataState: HOURLY_ALL` + the `HOUR` dimension, a 2025
API addition) — outside plan §3.3's fixed set; adding it later is a
purely additive constant-table change.

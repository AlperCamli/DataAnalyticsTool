---
doc_class: entity
status: draft
last_verified: null
aliases: [account, member, customer]
maps:
  - { object: supabase.public.users, role: system-of-record, keys: [id] }
join_guidance: per-target
sources:
  - "machine doc: supabase.public.users (PK id; auth_user_id unique)"
  - "app code: CV_Builder/frontend/src/app/integration/analytics.ts (gtag config sets no user_id; no User-ID set() call)"
  - "machine doc: ga4.standard.signedInWithUserId (User-ID feature flag dimension)"
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/users.md"
depends_on:
  - supabase.public.users
  - ga4.standard.signedInWithUserId
contamination: null
---

# user

## What it is

The person with a CVBuilder account — one row per `supabase.public.users`
(PK `id`; `auth_user_id` is the unique seam to Supabase auth). GA4 and GSC
see anonymous visitors and devices, not accounts.

## System map (routing table)

- `supabase.public.users` — **system-of-record.** Answers "who is this user,
  what do they own, what have they done": every owned table joins
  `user_id → users.id`. Identified, non-anonymous.
- GA4 — anonymous **device / session behavior** only. Answers "how many
  users/sessions, from where, doing what" in aggregate. It cannot name an
  account: the app calls `gtag('config', …)` with **no `user_id`** and never
  issues a User-ID `set` (analytics.ts), so GA4 User-ID is off —
  `ga4.standard.signedInWithUserId` is "no" for all traffic, and the Data API
  exposes neither a `userId` nor a `clientId` dimension to join on.
- GSC — search side, fully anonymous (queries, pages, impressions). No user
  concept at all.

Routing: per-user questions → Supabase only. GA4/GSC answer population-level
trends, never attributable to a `users.id`.

## Keys & join paths

- Within Supabase: `users.id` is the fan-out hub; every owned table carries a
  `user_id` FK to it. `auth_user_id → auth.users.id` reaches Supabase auth
  (outside this estate).
- **No Supabase↔GA4 blend key exists.** No GA4 user or client identifier is
  available (User-ID disabled; clientId is not a Data-API dimension), so there
  is no column/field pair that identifies the same person across the two
  systems. Do not invent one.

## Cross-source resolution rule

Because no shared identity key exists, **user identity cannot be blended or
agent-joined across systems** — neither Looker Studio blending nor ad-hoc
fetch-and-combine can attribute a GA4 row to a Supabase user. The only
cross-system move is **aggregate reconciliation**: compare independently
computed counts (e.g. GA4 new users / active users vs Supabase `users` rows)
over matching date ranges, by magnitude, never by key. Recurring "per-user"
reporting must be sourced entirely from Supabase.

## Caveats

- **Identity gap:** GA4 = anonymous devices (cookie/consent loss, multi-device,
  bots filtered client-side by a user-agent regex in analytics.ts); one person
  is not one client id. Supabase = accounts deduplicated by `id`.
- Deduplicate people by `users.id` (internal), not `auth_user_id`.
- `email` and `full_name` are PII (see `supabase.public.users`) — exclude from
  shared reporting slices.
- If User-ID is enabled later (app sends `user_id = users.id`), a real join
  becomes possible; today it is absent — see Ungrounded gaps in the PR body.

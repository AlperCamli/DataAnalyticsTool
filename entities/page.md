---
doc_class: entity
status: draft
last_verified: null
aliases: [url, web page, landing page, article]
maps:
  - { object: "gsc.standard.page",     role: search-identity,    keys: [page] }
  - { object: "ga4.standard.pagePath", role: analytics-identity, keys: [pagePath] }
join_guidance: per-target
sources:
  - "machine doc: gsc.standard.page (canonical URI — full URL incl. scheme+host)"
  - "machine doc: ga4.standard.pagePath (path only, hostname+query stripped); ga4.standard.pageLocation (full URL)"
  - "KB: systems/gsc/dimensions.md (byPage aggregation, canonical URI) + systems/ga4/dimensions.md"
  - "app code: CV_Builder/frontend/src/app/routes.tsx + src/content/career-advice-content.json (public routes/content are frontend-defined, not DB-backed)"
depends_on:
  - gsc.standard.page
  - ga4.standard.pagePath
  - ga4.standard.pageLocation
  - ga4.standard.fullPageUrl
  - supabase.public.cv_templates
contamination: null
---

# page

## What it is

A public web page of CVBuilder on `jobspecificcv.com` — the marketing/landing
pages, `/pricing`, and `/career-advice/:categorySlug/:articleSlug`. Both search
(GSC) and analytics (GA4) address pages by URL. **No Supabase table represents
these pages**: their content and routes are frontend-defined (`routes.tsx`,
`career-advice-content.json`). `cv_templates.slug` is a design-template id, not
a page URL.

## System map (routing table)

- `gsc.standard.page` — **search-identity.** Answers "how did this URL perform
  in Google Search" (clicks, impressions, position, query). Its value is the
  **canonical URI** Google selected — a full URL including scheme + host.
- `ga4.standard.pagePath` — **analytics-identity.** Answers "on-site behavior
  for this page" (views, engagement, events). Its value is the **path only**
  (hostname and query string stripped), e.g. `/career-advice/...`. Full-URL
  variants exist: `ga4.standard.pageLocation` (scheme+host+path+query),
  `ga4.standard.fullPageUrl` (host+path+query, no scheme).
- Supabase — **not a source for public pages** (see above).

Routing: search performance → GSC; on-site behavior → GA4; relate the two by URL.

## Keys & join paths

Documented blend key pair — normalize the GSC full URL to a path and match GA4
`pagePath`:

`path(gsc.standard.page) == ga4.standard.pagePath`, where `path()` = strip
scheme + host (`jobspecificcv.com`, including any `www.`/subdomain), strip a
trailing slash, drop `?query` and `#fragment`.

- The property is single-domain (`sc-domain:jobspecificcv.com`), so host is a
  constant and **path is a safe common key**.
- Alternative: blend GSC `page` ↔ GA4 `pageLocation` or `fullPageUrl` (both
  full URLs) — fewer transforms, but reconcile scheme (`pageLocation` has it,
  `fullPageUrl` does not) and query strings.

## Cross-source resolution rule

Row-level, per-page join **is** supported. Recurring reports → Looker Studio
blend of GSC `page` (normalized to path) with GA4 `pagePath` on the documented
key. Ad-hoc questions → agent fetches both, normalizes, and joins on path.
Prefer the path key — it is the most stable across the two URL shapes.

## Caveats

- **Canonicalization:** GSC `page` is Google's *canonical* URL, which can
  differ from the URL actually visited and recorded by GA4 — normalized paths
  may still not line up 1:1.
- **byPage aggregation:** grouping/filtering GSC by `page` forces `byPage`
  (you cannot aggregate by property), changing impressions/position (gsc
  dimensions).
- **Trailing slash / query / case:** GA4 `pagePath` excludes the query string;
  GSC canonical URLs usually have none — but trailing-slash and case
  differences cause misses, so normalize both sides.
- **Coverage:** GSC sees only pages that appeared in Search; GA4 sees only
  pages where the tag fired (bots excluded client-side). `(not set)` and
  sampling apply.
- **No Supabase leg** — see Ungrounded gaps in the PR body.
